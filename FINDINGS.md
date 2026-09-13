# Findings

The crash-matrix and revocation figures in sections 1–7 come from
`results/findings.json`, produced by `experiments/analyze.py` from the raw
trial logs. Section 8 uses `results/adjudication.json`. `make all` reruns
these synthetic experiments; their random baseline counts may change.
Section 10 instead uses archived live-model measurements in
`results/live_divergence.json`, collected by the separate opt-in
`experiments/run_live_agent.py` harness. `make all` does not make live calls
or reproduce those measurements.

Setup for the crash-matrix figures: 960 trials in which the process was confirmed
killed at the requested instruction (960/960 attempts; no trial is silently
dropped). Order value is 5000 cents. Grading compares the ledger against
the runtime's own report, so a runtime cannot pass by being confident.

---

## 1. Headline

| runtime | violations | rate | overpaid | books wrong | mean fsyncs |
|---|---|---|---|---|---|
| `naive` | 144 / 240 | 60.0% | $5,700 | 0 | 4.54 |
| `replay_position` | 83 / 240 | 34.6% | $2,660 | 19 | 3.45 |
| `replay_content` | 89 / 240 | 37.1% | $3,710 | 0 | 3.51 |
| **`anchored`** | **0 / 240** | **0.0%** | **$0** | **0** | 3.84 |

"Violation" means I1, I2 or I4 from CONTRACT.md failed: a duplicate
committed effect, an effect under a revoked scope, or a report the ledger
contradicts. "Books wrong" is the subset where exactly one effect committed
but the runtime told its operator a different number — no alert fires, and
reconciliation finds it next month.

The cost of the guarantee is about 0.4 extra fsyncs per workflow, roughly
12%, for the anchor writes. Recovery wall-clock is **not** reported: in this
harness it is dominated by Python interpreter startup and would be a
meaningless comparison between runtimes.

**On run-to-run variance.** The agent draws its decision from fresh entropy
in every process, deliberately, because a recovering process is not a
continuation of the crashed one. So the baseline rows move between runs.
Across five full 960-trial runs at `--reps 8` we have observed
`replay_position` between 34.6% and 38.3%, and `replay_content` between
32.5% and 37.1% — including runs where each was the worse of the two. Treat
the baseline figures as approximate to roughly ±3 points, and the ordering
between the two replay strategies as **not established**: they are two ways
of being wrong, not a ranking.

The table above is the run recorded in `results/findings.json` in this
repository. Running `make all` overwrites it with a new draw, and the
baseline rows will shift by a point or two. That is expected; if you want a
tight interval, raise `--reps` and report one.

The `anchored` row does not vary. Zero violations is a property of the
mechanism rather than a sample statistic: no draw of the agent's decision
can move an anchor that was fsynced before the agent was called.

---

## 2. The failure is concentrated where the service stops cooperating

Violations per 80 trials, by service tier:

| runtime | `idempotent` | `queryable` | `opaque` |
|---|---|---|---|
| `naive` | 48 | 48 | 48 |
| `replay_position` | 9 | 37 | 37 |
| `replay_content` | 15 | 37 | 37 |
| `anchored` | 0 | 0 | 0 |

Two things worth reading off this table.

`naive` is flat across tiers because it never supplies a caller key at all,
so a service that would happily dedupe for it gets no chance to. This is the
cheapest bug in the set and the most common one in production.

Both replay runtimes improve sharply on the `idempotent` tier and then
degrade. That is the correct and expected shape: a stable workflow-derived
key plus a cooperative service genuinely does fix most of this. **Replay is
not broken.** The residue on the best tier — 9 to 15 violations per 80,
depending on the runtime and the draw — is what section 3 is about.

---

## 3. The mechanism: a key derived from a decision is not a key

This is the finding.

Replay-based recovery is sound under one condition: every nondeterministic
value must be durable before it can influence an external effect. Frameworks
state this as "workflow code must be deterministic" and it is the developer's
job to honour it.

For an LLM agent the condition is easy to violate in a specific way, because
the model call reads like orchestration logic and people put it in workflow
code. `BELAY_JOURNAL_DECISION` toggles exactly that one variable, changing
nothing else:

| runtime | decision persisted first | decision inline |
|---|---|---|
| `naive` | 72 / 120 | 72 / 120 |
| `replay_position` | 32 / 120 | 51 / 120 |
| `replay_content` | 32 / 120 | 57 / 120 |
| `anchored` | 0 / 120 | 0 / 120 |

Violations rise by roughly 60–80% for both replay runtimes. `anchored` does
not move. This is the one comparison in the repo where a single variable is
isolated, so it is the one to trust most.

The causal chain, visible in `experiments/run_divergence.py` scenario A:

1. Agent decides: full refund, 5000. The value is live in memory only.
2. Runtime derives an idempotency key from the decision, `sha256(order |
   effect | 5000)`, and calls the service.
3. Service commits 5000. Process is SIGKILLed before the acknowledgement.
4. Recovery replays. The decision was never journaled, so the agent is
   re-invoked. This time it decides: split refund, 3000 + 2000 credit.
5. The key is now `sha256(order | effect | 3000)`. The journal has no match.
   The service has never seen this key either, so its dedupe does not fire.
6. A second refund commits. $80 has left on a $50 order.

The payment service in step 5 offers idempotency keys, and the runtime
supplied one. It still double-refunds, because the key it supplied was a
function of a value the model chose, and on recovery the model chose
differently.

**An idempotency key derived from a nondeterministic decision inherits that
nondeterminism, and a key that is not stable across restarts is not an
idempotency key.**

The two replay strategies fail in different directions, which is worth
seeing side by side (`run_divergence.py` scenario C):

- `replay_content` addresses journaled effects by content hash, so a diverged
  decision finds no match and **issues the effect again**. Money is wrong.
- `replay_position` addresses them by step index, so a diverged decision is
  handed the previous decision's receipt. Exactly one effect committed, but
  the runtime reports 3000 when 5000 left. Money is right, **books are
  wrong**, and nothing alerts.

There is no third option available to a replay runtime. The journal records
what the last run *did*; replay needs to know what this run *will* do.

Anchoring sidesteps the choice rather than solving it. The effect slots are
enumerated and fsynced before the agent is called, so the anchor is stable
whatever the model does next. Divergence becomes an observation rather than
a hazard.

---

## 4. Authorisation is not the kind of thing a journal can remember

Scenario: the agent plans a refund, the process dies, an operator revokes
the refund scope while it is down, the workflow restarts. Nothing had
committed.

| runtime | refunds issued under a revoked scope |
|---|---|
| `naive` | 0 / 16 |
| `replay_position` | **16 / 16** |
| `replay_content` | **16 / 16** |
| `anchored` | 0 / 16 |

Both replay runtimes model the authorisation check as a journaled activity
result, which is how it is written when authorisation is an RPC. On replay
the framework returns the cached grant as a deterministic fact and the
workflow proceeds. This is not the framework misbehaving; it is the framework
doing precisely what it promises, applied to a fact that was never safe to
treat as replayable.

`naive` scores well here for an uninteresting reason: having no journal, it
re-checks on every attempt. It buys authorisation freshness with the 60%
duplicate rate in section 1. It is not safe, just differently unsafe.

---

## 5. The availability cost, stated in full

`anchored` refuses to guess, and refusing has a price. Escalation rate — a
human paged, workflow halted — by tier:

| discipline | `idempotent` | `queryable` | `opaque` |
|---|---|---|---|
| decision persisted first | 0% | 0% | **60%** (24/40) |
| decision inline | 80% | 80% | 80% |

Read the top row first. On any service that offers either idempotency keys
or a post-hoc lookup, the availability cost of the guarantee is **zero**.
Cooperation from the service buys all of it back. The whole cost is
concentrated on the `opaque` tier, and CONTRACT.md §4 proves that residue is
irreducible: the two worlds "never sent" and "sent, acknowledgement lost"
are indistinguishable under every observation available.

Sharper still: of the 24 opaque-tier escalations, **8 page a human about an
effect that never committed.** One third of the on-call burden is a false
alarm, and it is provably impossible to remove without changing what the
service will tell us. That is the honest shape of the result.

The bottom row is the robustness test. Under the same developer error that
doubles the replay runtimes' violation rate, `anchored` still commits nothing
twice; it degrades to resolving the in-flight effect and then halting,
because it cannot know what else was intended. **The failure mode changes
from a silent duplicate to a loud stop.** That trade is the product.

---

## 6. A bug the harness found

Worth recording because it is the best evidence the harness tests something
real.

The first version of `resolve_ambiguous_refund` handled the `idempotent`
tier by re-issuing the refund under the same anchor, reasoning that this is
idempotent and therefore safe. It is safe against duplication. It is unsafe
against authorisation: if the original call never landed, the "retry" is the
first and only call, and it was made with no live permission.

`run_revocation.py` caught this immediately, at 50% — every trial that
crashed at `after_intent`.

The fix separates the two rungs of the ladder, and the distinction is the
part worth keeping:

- A **query** asks the service what already happened. It creates nothing,
  needs no permission, and is always safe.
- A **completion** issues the effect because the query proved it never
  landed. That is a new external effect and needs a live permission, exactly
  as a first attempt would.

"Idempotent" is a property of duplication, not of authorisation. Treating a
reconciliation retry as a free action because the service dedupes is a
category error, and one we would not have noticed by reading the code.

---

## 7. Limitations

Things a reader should hold against this work.

**Measurement is not proof.** I1–I4 hold across 960 crashes at seven named
instruction boundaries that we chose. A boundary we did not think of is not
covered. Only CONTRACT.md §4 is proved.

**The baseline rates are not precise.** See the variance note in section 1.
The claim that rests on them is qualitative — replay violates the contract
at a rate in the low-to-high tens of percent, where anchoring violates it at
zero — and that gap is far wider than the noise. Anyone wanting a tight
interval on the baselines should raise `--reps` and report one; we have not.

**No concurrency.** One workflow instance at a time. Two processes
recovering the same journal would need a lease, and I1 does not hold without
one. This is the largest gap.

**Process death, not machine death.** SIGKILL leaves the OS page cache
intact, so a committed SQLite transaction is durable with certainty. Real
power loss would test `fsync` in a way we do not.

**The crash-matrix agent is simulated.** Two plans, drawn per process from
`os.urandom`. The matrix tests the runtime's response to divergence; its
frequency is an input, not a measured production rate. The separate live
experiment in section 10 now measures decisions under fixed model and
prompt settings. Its original three N=50 conditions observed no decision
divergence. That complicates the premise that divergence is frequent; it
does not establish that production agents are deterministic. The live
harness stays outside the runtime and recovery path.

The optional OpenAI recovery adapter and recorded recovery desk are additional
ways to exercise `second/`. They do not change the provenance of the published
numbers. Live-model runs must report their own resolution, abstention, false
resolution, and request-usage measurements. Dossier revision checks prevent
sequential duplicate or stale application; concurrent execution remains outside
the failure model.

**Services are mocks, written to a stated contract.** They are not
strawmen — each tier implements its semantics including the ones that make
recovery impossible — but a real processor will have behaviours none of
them do.

**The 2-of-2 workflow is small.** Two effect slots, one branch. Anchoring
requires enumerating effect slots before the decision, and it is an open
question how that scales to an agent whose *number* of actions is itself
model-chosen. We think the answer is a bounded slot pool with refusal on
exhaustion, and we have not built it.

---

## 8. Closing the escalation hole

Section 5 measures the availability cost of I3: on the `opaque` tier,
`anchored` halts 60% of the time, and the halt is a dead end. `second/`
adjudicates those halted anchors against out-of-band records. The full
account is in [docs/SECOND.md](docs/SECOND.md); the numbers are here.

400 adjudications of anchors `anchored` really halted on, after a real
SIGKILL. Graded against the ledger, never against the adjudicator's report.
Both rows below run the same agents over the same evidence; the only
difference is whether the agent's conclusion is verified.

| pipeline | cases | closed | abstained | violations | duplicate refunds | overpaid |
|---|---|---|---|---|---|---|
| `trusting` | 200 | 108 | 79 | **13** | 7 | $210 |
| `validated` | 200 | 90 | 110 | **0** | 0 | $0 |

The 13 violations are the two failure modes from section 1 reappearing one
level up, which is the part we did not expect. Seven are duplicate refunds:
the agent read a settlement report whose cutoff preceded the attempt, found
silence, concluded absence, and paid twice (I1). Six are books-wrong: the
agent asserted commitment citing a digest nobody produced, the anchor
closed, and the ledger holds nothing (I4). "Money wrong" and "books wrong"
are not properties of replay. They are what happens whenever something
nondeterministic is allowed to own an outcome.

**Agent quality costs availability, not correctness.** On the tiers where
the answer is knowable, the validated pipeline behaves like this:

| agent profile | anchors closed | abstained |
|---|---|---|
| `competent` | 16 / 16 | 0 |
| `hallucinating` | 16 / 16 | 0 |
| `overconfident` | 16 / 16 | 0 |
| `lazy` | 12 / 16 | 4 |
| `adversarial` | 12 / 16 | 4 |

Hallucination is free: a fabricated pointer resolves to nothing, costing
one to two wasted fetches per case and changing no outcome. Overconfidence
is free: 42 unsupported verdicts were rejected over the run and every one
became an abstention. Only laziness costs anything, and what it costs is
resolution — an agent that never asks what a source *covers* cannot
establish absence, so it leaves resolvable anchors halted. It is never
wrong about them.

That asymmetry is the whole result, and it comes from constraining the
agent's output surface rather than from improving the agent. It emits
pointers, a three-way verdict, and prose. It cannot name an anchor, an
amount, or a scope; those come from the journaled intent. Pointers are
fetched deterministically, so a fabricated one is inert. Verdicts are
checked against what was actually fetched, so an unsupported one abstains.

**What did not change.** With no out-of-band records the adjudicator
resolves nothing — 0 of 40 — which is CONTRACT.md §4 holding exactly as
stated. The proof is about what is decidable from inside the process given
the journal and the service API. Widening the input does not repeal it, and
`stale_settlement` is the honest demonstration: a report that is perfectly
truthful and completely uninformative about the window in question resolves
0 of 40 under validation, because nothing there vouches for the silence.

The trusting pipeline closes cases on that tier, and it cannot do otherwise.
The only thing distinguishing a stale report from a complete one is a
coverage claim, and a pipeline that does not check coverage cannot see the
difference — both look like a report it searched and found nothing in.
Whether any particular closure turns out to be right is then settled by
whether the effect happened to commit, which is luck rather than evidence.
Some of them are correct, and that is the point: an adjudicator can be right
for no reason, and a rate of being right for no reason is not a safety
property.

All 90 closed anchors resumed to a committed workflow report. 110 of 200
still need a human. The claim is only that the halt is now the floor rather
than the whole outcome.

**On run-to-run variance.** Both agents in this section draw fresh entropy
per process, so most of the figures above are sample statistics and will
move when you re-run. What moves: the trusting control's violation count
and its split into duplicates and books-wrong; the overpaid figure; every
per-tier and per-profile close rate; the wasted-pointer means. Read those
for magnitude and direction, not as point estimates — `make adjudication`
overwrites them with a new draw, exactly as `make all` does to section 1.

Two things do not move, and this section is about them rather than about the
rates.

- **The validated pipeline's zero.** No draw of an agent's conclusion can
  produce a citation that was never fetched, or a coverage claim a manifest
  does not make. Zero false resolutions is a property of `validate`, not a
  sample statistic, in the same way that `anchored`'s zero in section 1 is a
  property of anchoring.
- **The coverage asymmetry.** `none` and `stale_settlement` resolve nothing
  under validation in every draw, because no source in either tier vouches
  for its own silence. `webhook_only` closes some anchors and can never
  close all of them, because a lossy source confirms and never exonerates.
  Those are entailments of the table in docs/SECOND.md §4, not measurements.

The *direction* of the headline comparison is also stable, though not by
proof: the control's violation count varies and has not yet been zero across
the runs we have done. `experiments/check_docs.py` fails the run if it ever
is, on the grounds that a control which makes no mistakes demonstrates
nothing.

---

## 9. What we would do next, in order

1. **Broaden the live measurement.** Section 10 reports the first completed
   measurements, including the null result. Extend the standalone harness
   to representative agent tasks and complete higher-capability model
   conditions when quota permits. Measure each model, prompt and setting
   separately; do not select prompts for producing divergence. The rate
   determines exposure to divergence-triggered replay failures, not the
   correctness of allocating stable effect identity before the decision.
2. **A lease, and then the concurrency claim.** The single-instance
   assumption is the weakest thing in CONTRACT.md.
3. **Unbounded effect slots.** Whether anchoring survives an agent that
   decides how many actions to take. If it does not, say so.
4. **Measure the live recovery adapter.** Section 8 is parameterised by the
   agent's vices precisely so the safety result does not depend on the
   model, but the *resolution* rate does. The optional adapter already exists
   in `second/live_agent.py`; use `experiments/evaluate_recovery.py --agent
   openai` to measure its resolution, abstention, false-resolution and request
   usage rates. Its live effectiveness has not yet been measured here.
5. **Reduce the false-alarm third.** The 8-in-24 false escalations are
   irreducible given what an opaque service tells us, but a
   write-ahead-to-a-cooperating-proxy pattern might convert an opaque tier
   into a queryable one. That would move the cost rather than remove it,
   and the trade should be measured.

---

## 10. Live decision divergence

**The original live measurement did not confirm frequent divergence.** In
three completed N=50 conditions, every decision within a condition agreed.
The evidence is a bound under those settings, not a claim that the true
rate is zero. All requests, raw provider responses, assistant output,
parses, failures and configuration are retained in
[results/live_divergence.json](results/live_divergence.json). Earlier runs
are preserved in `previous_runs`; partial availability checks are not
combined with completed measurements.

**What was measured.** The opt-in standard-library harness sends identical,
stateless refund requests to Google's OpenAI-compatible Chat Completions
endpoint. Every request in a condition has the same recorded body hash.
The harness uses no response cache, fixed seed, conversation history or
prompt adaptation. The two possible decisions are `full_refund` (5000 cents
cash) and `split_refund_plus_credit` (3000 cents cash plus 2000 cents credit).
These imply different refund amounts and different numbers of effects.

The fixed `borderline` scenario is a working order that arrived three days
late with a cosmetic mark; the customer accepts either remedy and expects
to shop again. In `clear_cut`, verified damage makes the order unusable,
and the customer explicitly requests a full cash refund and rejects
credit. These scenarios were fixed before the first live call. The exact
system and user text is stored with each run.

**Original completed run.** Requested and returned model:
`gemini-3.1-flash-lite`; `reasoning_effort: minimal`;
`max_completion_tokens: 1024`. The system asks for a fair remedy and ends
with a request for a JSON object containing only `decision`, with no
explanation. These are three separate measurements; N is captured model
responses, and API failures are counted separately.

| prompt / output instruction | temperature | N | full / split | unparseable | API failures | pairwise disagreement | P(split), among parseable |
|---|---:|---:|---:|---:|---:|---:|---:|
| `borderline` / JSON only | 1.0 | 50 | 0 / 50 | 0 / 50 | 0 / 50 attempts | 0% (N=50) | 100% (N=50) |
| `borderline` / JSON only | 0.0 | 50 | 0 / 50 | 0 / 50 | 0 / 50 attempts | 0% (N=50) | 100% (N=50) |
| `clear_cut` / JSON only | 1.0 | 50 | 50 / 0 | 0 / 50 | 0 / 50 attempts | 0% (N=50) | 0% (N=50) |

**Explanation comparison.** The completed explanation condition also used
requested and returned model `gemini-3.1-flash-lite`, minimal reasoning,
temperature 1.0, the original `borderline` scenario and a 1024-token output
limit. Only the system's output instruction changed: explain the
recommendation briefly, then end with `Decision: <label>`. There was no
JSON requirement. The parser reads that final marker, not labels mentioned
in the explanation. A fresh N=50 JSON control used the original request
body; it followed the explanation block rather than being randomly
interleaved. Both blocks completed on September 13, 2026, between 16:27
and 16:36 UTC, configured for five-second pacing within each block, with no
retries needed. Together with nine larger-model availability attempts, the closeout
used 109 new attempts against a predeclared cap of 129, including failures.

| prompt / output instruction | temperature | N | full / split | unparseable | API failures | pairwise disagreement | P(split), among parseable |
|---|---:|---:|---:|---:|---:|---:|---:|
| `borderline` / explanation then decision | 1.0 | 50 | 0 / 50 | 0 / 50 | 0 / 50 attempts | 0% (N=50) | 100% (N=50) |
| `borderline` / fresh JSON control | 1.0 | 50 | 0 / 50 | 0 / 50 | 0 / 50 attempts | 0% (N=50) | 100% (N=50) |

All 50 explanation texts were distinct, but all 50 final decisions were
the same. Generated explanations varied; the chosen action did not. This
N=50 sample does not support the suggestion that requesting JSON alone
explains the original stability. It does not show that output instructions
never affect decision variance, and generated explanations are not a
measurement of internal reasoning.

**How strong is the null result?** For each completed N=50 cell above, the
one-sided 95% upper confidence bound on pairwise disagreement is
`1 - 0.05**(1/25) = 0.112928…`, or **11.3%**. This uses 25 disjoint pairs
with no disagreements, assuming independent, stationary invocations. The
1,225 overlapping comparisons from N=50 calls are not 1,225 independent
trials. The result is therefore "an upper bound of 11.3% under these
conditions", not "zero divergence" or "below 11%". It does not exclude
smaller rates that could matter in production.

The primary estimator is the fraction of all unordered response pairs
whose parsed categories differ, treating `unparseable` as a third category.
The report also gives disagreement restricted to valid decisions, the
parse-failure fraction, and API failures separately. Unparseable outputs
are never silently dropped; two unparseable texts may themselves differ.
The simulator's `BELAY_NONDET_P` is **P(split)**, not pairwise disagreement.
For a binary population with P(split) = p, disagreement is `2p(1-p)`; the
finite-sample all-pairs estimator and this plug-in expression need not be
identical. These are conditional measurements of returned responses, not
production failure probabilities.

**Higher reasoning: quota and availability, not findings.** On September
13, 2026, we retried the exact model strings below with
`reasoning_effort: high`, JSON output, `borderline`, temperature 1.0 and
`max_completion_tokens: 16384`. No model was substituted:

- `gemini-3.1-pro-preview`: no model response in one attempt. HTTP 429
  reported a quota limit of zero. This establishes a quota block, not that
  the model name is invalid.
- `gemini-3.8-flash`: one model response in four attempts, with three HTTP
  503 failures. The successful response returned that exact model string.
- `gemini-3.7-flash`: two model responses in four attempts, with two HTTP
  503 failures. Both returned that exact model string.

The project's Google AI Studio rate-limit page still showed zero allowance
for Pro and a limit of 20 requests per day for each larger Flash model.
Even a daily reset would not permit a same-day N=50 condition on either
Flash model. We retained N=50 as the target but capped each Flash
availability check at four attempts; the remaining temperature/scenario
cells were not attempted. An extended collection window or increased quota
is needed. These partial checks do not appear in the findings tables and
provide no useful divergence estimate. Every HTTP 503 is saved before a
bounded retry with increasing delays; failures consume the attempt budget.
HTTP 429 stops immediately. The quota observations and per-model attempt
counts are also recorded in the result metadata.

The earlier high-effort follow-up remains archived: 20 attempts, 11 model
responses and nine API failures, including the zero-quota Pro attempt.
Its small cells are not findings. Two explanation-mode responses had
different explanation text and the same final decision (an observation at
N=2). A separate clear-cut cell had just one model response and one API
failure, not two responses: its correct full-refund JSON was wrapped in
Markdown fences and rejected by the old strict parser. That is a formatting
observation at N=1. The new parser accepts a single outer JSON fence while
still rejecting duplicate keys, extra keys and conflicting formats. The
archived rejection is preserved with its original parser version; it has
not been reclassified to improve the numbers.

**Scope and interpretation.** The original study used the smallest model
we tested, minimal reasoning, two supplied remedies and the most restrictive
output instruction we tested. That may favor stable decisions, but we
have not established that it is the least-divergent possible configuration.
The JSON requirement was system-prompt text: the request contains no
`response_format`, schema or API-enforced constrained decoding. An
explanation comparison tests the effect of that output instruction. It
cannot by itself establish the effect of constrained decoding, reveal
internal reasoning, or settle whether production agents are stable.
Model aliases, provider behavior and temporal dependence also limit the
independence assumption. Different settings and prompts are not pooled
into one rate.

**Why the mechanism still matters.** Anchoring allocates and durably records
effect identity before consulting the model. Within the stated contract
and single-instance assumptions, that identity remains stable regardless
of how often the model changes its decision. The divergence rate determines
how often divergence-triggered replay failures bite; it does not determine
whether the identity-allocation fix works. The crash matrix demonstrates
the mechanism under simulated divergence and the tested crash boundaries.
The live experiment does not establish that divergence is frequent in
production, and neither experiment extends the guarantee to concurrency or
other assumptions the contract excludes.
