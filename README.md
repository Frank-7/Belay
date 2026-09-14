# Belay

**Find out what an interrupted AI action actually did, and what can safely happen next.**

**[Visit the Belay website](https://frank-7.github.io/Belay/)** for an
interactive introduction, recorded recovery walkthroughs, and inspectable evidence.
The public site runs on GitHub Pages; the Payment Mission MVP and Recovery Desk
run locally.
See [website build and deployment](docs/WEBSITE.md) to develop the site.

To belay is to secure the rope before the climber moves. The protection goes
in ahead of the fall, not after it. The nautical sense is the other half of
the contract: *belay* also means stop.

---

## Try the Payment Mission MVP

The **Belay Payment Mission MVP** turns an open-ended payment request into a
plan the customer can inspect, correct and authorize. Ask it to pay an invoice,
bill, insurance premium, tax obligation, subscription, transfer, ticket order
or another purchase. Belay leaves unknown payees, amounts and required
references blank. After one exact approval, the customer view and backend view
follow the same durable event through policy checks, a simulated USDC hold, a
simulated USDC-to-USD payout and a linked receipt.

```bash
python -m purchase_simulator.server --port 8777
# Open http://127.0.0.1:8777
```

See [MVP instructions and architecture](docs/PURCHASE_SIMULATOR.md). The
browser talks to a real loopback server and persists each mission, event,
single-use value movement and provider result in SQLite. The request extractor,
authorization signature, wallet, USDC transfer, conversion, bank payout and
payee confirmation are fictional local fixtures. No model, blockchain, bank,
government agency, insurer, biller, merchant or external API is connected. A
tax receipt confirms only the simulated payment; an insurance receipt confirms
only the simulated premium payment.

The investor experience uses the `belay.mission.v0.1` simulation schema. The
earlier `belay.purchase.v0.3` ticket routes remain for compatibility. A live
product still requires authenticated users, custody and settlement providers,
verified payee adapters, compliance review and production cryptography. Read
the [mission presentation](docs/MVP_PRESENTATION.md),
[USDC settlement architecture](docs/USDC_SETTLEMENT_ARCHITECTURE.md) and
[integration guide](docs/INTEGRATION.md).

## Start the Recovery Desk

Belay is an **AI Apps prototype for an operator investigating an uncertain
action**. Open an incident, ask the evidence assistant for an explanation,
inspect the validator's checks, then record a supported outcome or request
the specific evidence still missing. The assistant never holds payment keys
or authorizes its own proposal.

From this clone, with Python 3.10 or newer:

```bash
python -m recovery_app.server --port 8766
# Open http://127.0.0.1:8766
```

The app shares the research JSONL journal, evidence validator and guarded
application path. Local demo scenarios include a lost acknowledgment,
confirmed absence, stale reports, conflicting sources and revoked permission.
They make real local SQLite writes with a controlled interruption; they are
not new OS-crash trials. The deterministic baseline needs no credentials.
Set `OPENAI_API_KEY` and an explicit `OPENAI_MODEL` in the server environment
to enable the real model proposer. Each investigation makes at most two
model requests; provider failures remain visible and do not trigger payment
or model retries. The interface labels which proposer actually ran.

**Public blockchain option:** connect MetaMask to Arc Testnet, fund it with
free test USDC from Circle, and approve a 0.01–1.00 test-USDC transfer. Belay
saves its intent before the wallet request and recovers the finalized receipt
without sending again. Wallet keys stay in MetaMask; this is human-authorized
testnet recovery, not autonomous custody, escrow or real-dollar settlement.
See [free test-wallet setup and guarantees](docs/TEST_WALLET.md).

GitHub Pages includes a **recorded operator walkthrough** using this same UI;
it cannot run Python, make model requests or initiate a wallet transfer.
See [integration boundaries](docs/INTEGRATION.md),
[final demo and pitch](docs/FINAL_PRESENTATION.md), and
[next-stage plan](docs/NEXT_STAGE.md).

```bash
python tests/test_recovery_app.py
python tests/test_arc.py
python experiments/evaluate_recovery.py --out tmp-runs/recovery-evaluation.json
python experiments/recovery_holdout.py --out tmp-runs/recovery-holdout.json
```

These reports separate useful resolutions, false resolutions, refusals and
abstentions. The frozen adversarial suite is classification-only and becomes
regression evidence after publication; repeated fixtures are not new holdout
incidents. No customer time savings or live-model improvement is assumed.

## Earlier Recovery Lab

The earlier runnable application below is a separate local recovery
simulation. The current pitch leads with the Payment Mission MVP and preserves
the Recovery Desk as the implemented investigation path for uncertain actions.
There is no live coverage, bank connection, autonomous wallet or ticket
checkout.
Start with the [document index](docs/INDEX.md),
[current architecture](docs/AUTONOMOUS_APP_ARCHITECTURE.md), and
[next-stage plan](docs/NEXT_STAGE.md).
The [integration guide](docs/INTEGRATION.md) maps the existing components and
the interfaces that future agent and guarantee services must respect.

The **Recovery Lab** is a local application for exploring one concrete case:
an agent intends a $50 partial refund on a $100 order, then crashes around
the payment request. Its **Activity** view keeps the intent, provider
receipts and recovery decision together for an operator.

```bash
python -m prototype.server --port 8765
# Open http://127.0.0.1:8765
python -m unittest discover -s tests -p "test_prototype.py" -v
```

The prototype supports Windows, Linux and macOS with Python 3.10+ and no
third-party dependencies. It makes real HTTP requests to a **fictional local
provider**; all money and agent decisions are simulated. Compare Belay,
the provider's existing stable-key retry, and an unprotected fresh-key retry.
Try a lost reply, a crash before sending, revoked permission, an opaque
provider, or a successful request.

This is a separate implementation of the pattern using SQLite, not a
production wrapper around the research runtime below. See
[prototype instructions and boundaries](docs/PROTOTYPE.md) and the
[repository evaluation](docs/REVIEW.md), including the history of two runtime
defects fixed by PR7 and the remaining limits of reported metrics.
The original SIGKILL experiments still require POSIX.

## The problem

An agent calls a payment API. The process dies between the call landing and
the acknowledgement coming back. On restart, nothing in the journal says
whether $50 left the company.

Durable execution frameworks solve this by replaying the workflow from a
journal of completed steps. That is sound under one condition, which every
one of them states plainly in its docs: **workflow code must be
deterministic.**

Put an LLM in the workflow and the decision *is* the control flow. Replay
re-invokes the model, the model decides differently, and recovery now has to
reconcile a journal describing what the last run did against a run that is
about to do something else. There are two ways to do that and both are
wrong:

- Match journaled effects **by content** and a diverged decision finds no
  match, so the effect is issued again. The money is wrong.
- Match them **by step position** and a diverged decision is handed the
  previous decision's receipt. The money is right, the books are wrong, and
  nothing alerts.

The journal records what the last run *did*. Replay needs to know what this
run *will* do.

## The claim

> An idempotency key derived from a nondeterministic decision inherits that
> nondeterminism, and a key that is not stable across restarts is not an
> idempotency key.

## The fix

Allocate effect identity **before** the model is consulted.

A workflow enumerates its effect slots up front and fsyncs an opaque anchor
for each one. The anchor is the effect's identity. It is not derived from the
decision, so a diverged decision cannot move it. The model chooses the
*amount*; it does not get to invent effect identities. An effect with no
anchored slot is refused.

Recovery then reads the journal rather than re-deriving intent by re-running.
The agent is re-invoked only when the journal proves no intent was ever
durable — which means nothing external can have happened. Divergence becomes
an observation instead of a hazard.

```
replay:    decide ──▶ derive key ──▶ call ──▶ 💀 ──▶ decide again ──▶ different key ──▶ call again
anchored:  anchor ──▶ decide ──▶ call under anchor ──▶ 💀 ──▶ read journal ──▶ reconcile that anchor
           ^^^^^^ fsynced before the model is ever called
```

## Results

These are the original committed synthetic experiment results. They are not
customer loss rates, production guarantees or inputs sufficient to price
customer reimbursement. See [the review](docs/REVIEW.md) for fixed historical
defects and remaining limitations of the grader and overhead measurements.

960 trials, each a real SIGKILL at a named instruction boundary, graded
against an external ledger rather than against the runtime's own report.
Order value $50.

| runtime | contract violations | overpaid | books wrong |
|---|---|---|---|
| naive retry | 144 / 240 — 60.0% | $5,700 | 0 |
| replay, position-matched | 83 / 240 — 34.6% | $2,660 | 19 |
| replay, content-keyed | 89 / 240 — 37.1% | $3,710 | 0 |
| **anchored** | **0 / 240 — 0.0%** | **$0** | **0** |

Permission revoked while the workflow was down: both replay runtimes issued
a refund under a revoked scope **16 / 16** times. Anchored refused 16 / 16.

Recorded accounting: about 0.4 extra fsyncs per workflow (~12%); this omits
work performed by killed workers before an outcome file was written and is
not full-workflow overhead. **With persisted decisions**, the tested
cooperative providers had 0% escalation, rising to 60% on the opaque provider.
Inline decisions still escalate on cooperative providers. These are selected
synthetic conditions, and the current grader does not cover every credit-slot
invariant; see CONTRACT.md and docs/REVIEW.md for the precise scope.

That 60% is a halt, and a halt is a dead end: a human gets handed a hex
string. `second/` is an agent that debugs the halted agent — it searches
out-of-band records for the fact the service will not disclose. 400
adjudications of anchors `anchored` really halted on, graded against the
ledger:

| pipeline | anchors closed | still halted | contract violations | overpaid |
|---|---|---|---|---|
| trusting the agent | 108 / 200 | 79 | **13** | $210 |
| **verifying the agent** | **90 / 200** | 110 | **0** | **$0** |

Same agents, same evidence; the only difference is whether the conclusion is
verified. And the result that matters is not the zero — it is that agent
quality moved the *closed* column and never the *violations* column. A
hallucinating adjudicator is free, because a fabricated pointer resolves to
nothing and cannot be cited. An overconfident one is free, because an
unsupported verdict becomes an abstention. A lazy one costs resolution and
nothing else. **[docs/SECOND.md](docs/SECOND.md)**.

The baseline rows move by a couple of points between runs, because the agent
draws fresh entropy per process by design, and `make all` will overwrite the
committed numbers with a new draw. The same is true of both adjudication
rows above, for the same reason. Two figures do not move: `anchored`'s zero
violations, and the verified adjudicator's zero false resolutions. Both are
properties of their mechanism rather than sample statistics — no draw of a
decision can shift an anchor that was fsynced before the model was called,
and no draw of an agent's conclusion can supply a citation that was never
fetched.

After a fresh draw the committed tables will disagree with `results/`, and
`make checkdocs` will say exactly which figure is stale. `make reset-results`
prints the list of tables to update.

Full numbers, the mechanism, and what we got wrong: **[FINDINGS.md](FINDINGS.md)**.
The exact guarantee and its failure model: **[CONTRACT.md](CONTRACT.md)**.

## What this is not

Stated up front so nobody has to go looking.

- **Not a claim that durable execution is broken.** Replay plus a stable
  workflow-derived key plus a cooperative service genuinely fixes most of
  this, and our numbers show it. The claim is narrower: replay is correct
  under a discipline that nothing enforces and no test surfaces, and
  anchoring removes the need for the discipline.
- **Not exactly-once.** Nobody has that. We offer *exactly-once up to
  escalation*, and we prove the escalation is necessary rather than
  conservative.
- **Not a framework.** One workflow, two effect slots, three service tiers.
  Enough to test a guarantee, not enough to deploy.
- **Not a claim about model quality.** Whether the refund decision was
  *correct* is a separate question from whether it was executed once and
  authorised.
- **Not a repeal of the impossibility proof.** `second/` widens the evidence
  admitted rather than defeating the argument. Given no out-of-band records
  it resolves nothing, and 110 of 200 adjudications still end with a human
  holding the anchor.

## Install

**Requirements**

| | |
|---|---|
| Python | 3.10 or newer (tested on 3.10 and 3.12) |
| OS | Linux, macOS, or WSL |
| Dependencies | none — standard library only |
| Network | Simulations use local data; the Recovery Lab uses loopback HTTP; optional recovery and decision models use external APIs |

> **Linux, macOS or WSL only.** The experiments send a real `SIGKILL`, and
> Windows has no such signal. A catchable exception would let `finally`
> blocks run and quietly repair the very states under study, so this is not
> a substitution we can make. `belay/chaos.py` exits with an explanation
> rather than a confusing `AttributeError` if you try.

Clone or download this repository, then:

```bash
cd belay
make test          # 42 contract assertions under real SIGKILL   (~30s)
make test-second   # adjudicator safety and stale recovery checks
```

There is nothing to install. If the contract suite prints `42 passed, 0 failed`
and the adjudicator suite also reports `0 failed`, you are set up.

Optionally, for linting only:

```bash
pip install -e ".[dev]" && ruff check .
```

## Run

```bash
make test          # contract invariants, under real SIGKILL          (~30s)
make test-second   # the adjudicator's safety properties              (~15s)
make demo          # the mechanism, one trial at a time, annotated     (~10s)
make adjudication  # escalated anchors, adjudicated and graded         (~2m)
make all           # everything above + analysis + viewer              (~5m)
open viewer/trace.html
```

Every command has a direct equivalent, if you would rather not use `make`:

```bash
python3 tests/test_contract.py
python3 tests/test_second.py
python3 experiments/run_divergence.py                  # the mechanism, explained
python3 experiments/run_matrix.py --reps 8             # 960 trials
python3 experiments/run_revocation.py --reps 8
python3 experiments/run_adjudication.py --reps 4       # 400 adjudications
python3 experiments/analyze.py                         # regenerates every quoted number
python3 viewer/build_viewer.py
```

`make all` rewrites `results/*.json` and `viewer/trace.html`. Baseline
numbers will differ slightly from the committed run; see FINDINGS.md §1 on
variance. `make clean` preserves these results; update the published tables
if you intend to commit a new experimental draw.

### Poking at it directly

Single trials are one function call, which is the fastest way to get a feel
for the failure modes:

```python
from experiments.harness import run_trial
import tempfile

base = tempfile.mkdtemp()

# Content-keyed replay, best service tier, decision not persisted before use.
t = run_trial(base, "replay_content", "idempotent", "in_flight",
              journal_decision=False,
              force_plans=("full_refund", "split_refund_plus_credit"))
print(t.verdict, t.refund_amounts)   # duplicate_effect [5000, 3000]

# Same crash, same service, anchored.
t = run_trial(base, "anchored", "idempotent", "in_flight",
              journal_decision=False,
              force_plans=("full_refund", "split_refund_plus_credit"))
print(t.verdict, t.refund_amounts)   # escalated [5000]
```

Runtimes are `naive`, `replay_position`, `replay_content`, `anchored`.
Service tiers are `idempotent`, `queryable`, `opaque`. Crash points are
listed in `belay/chaos.py`.

## Use the pattern in your own code

This repo is a research artifact, not a library: the workflow in
`belay/runtimes/anchored.py` has its effect slots hard-coded, because the
goal was to measure a guarantee rather than ship an abstraction. What
transfers is the pattern, and `examples/minimal.py` is the pattern at its
smallest — a charge-then-email workflow, about 120 lines, runnable:

```bash
python3 examples/minimal.py                            # clean pass
BELAY_CRASH_AT=in_flight   python3 examples/minimal.py  # crash, then recover
BELAY_CRASH_AT=after_intent python3 examples/minimal.py
```

Adapting it to your own workflow is four changes:

1. **Enumerate your effect slots as a constant** and fsync an anchor for each
   before you call the model. An effect with no anchored slot gets refused,
   not accommodated.
2. **Pass the anchor as the idempotency key or client reference.** Never a
   hash of anything the model chose.
3. **Recover by projecting the journal**, not by re-running the workflow. Only
   re-invoke the model when the journal proves no intent was ever durable.
4. **Split your reconciliation into queries and completions.** A query asks
   the service what happened, creates nothing, and needs no permission. A
   completion issues the effect because the query proved it never landed —
   that is a new effect and needs a live permission check. Collapsing these
   two is a real bug; we shipped it and the harness caught it
   (FINDINGS.md §6).
5. **If you put a model on the escalation queue, let it produce pointers and
   never conclusions.** Fetch what it points at, and admit the retrieved
   artefact rather than the model's summary of it. Require a source to vouch
   for its own coverage before silence is allowed to mean absence. Keep the
   amount and the scope on the journal side. That is the whole of
   `second/`, and it is what makes a hallucinating adjudicator merely
   useless (docs/SECOND.md).

The hard part is not the code. It is knowing which of your services is
`idempotent`, `queryable`, or `opaque`, because that determines which
guarantees are available to you at all. CONTRACT.md §4 proves what happens
on the third one.

## How the harness works

The part that makes the numbers mean anything.

**Crashes are real.** `belay/chaos.py` sends `SIGKILL` to its own process
at one of seven named call sites. Not an exception — an exception is
catchable and lets `finally` blocks run, which would quietly repair exactly
the states we are studying. Exit status 137 is how the harness confirms the
crash landed where it asked. All 960 trials did; none are silently dropped.

**Grading is external.** `services/ledger.py` is a SQLite table recording
what the outside world actually did. Nothing under `belay/` may read it
during a run. A runtime that reports "refunded $50" while the ledger holds
one $30 refund has not been unlucky; it has told its operator something
false, and it is scored as a violation.

**One variable at a time.** All four runtimes execute the same business
logic against the same services and the same journal implementation, so
differences come from recovery semantics and nothing else. The
decision-journaling discipline is a single environment toggle applied
identically to every runtime, including ours.

**The baselines are not strawmen.** `replay_content` is the better
engineering instinct and the strongest baseline: content-hashed keys fix the
mis-attribution bug in `replay_position`, which is why people reach for
them. It gets its own section in FINDINGS.md explaining why it is a
reasonable thing to have built.

## Repo map

```
CONTRACT.md               failure model, invariants, impossibility proof, out-of-scope
FINDINGS.md               measured results, the mechanism, the bug we shipped, limits
docs/SECOND.md            the adjudicator: closing the escalation hole
docs/CHECKPOINTS.md       what changed at each 12-hour checkpoint
examples/minimal.py       the pattern applied to a different workflow, runnable

belay/
  journal.py              append-only, fsync per record, plus a read-only trace sidecar
  chaos.py                SIGKILL at seven named instruction boundaries
  effects.py              typed effects, scopes, reversibility, service cooperation tiers
  authz.py                permission store outside the process, revocable mid-flight
  agent.py                the nondeterministic decision; draws fresh entropy per process
  runtimes/
    base.py               shared context and the reconciliation ladder
    naive.py              baseline 1 — retry on restart
    replay_position.py    baseline 2 — replay, journaled results matched by step index
    replay_content.py     baseline 3 — replay, matched by content hash
    anchored.py           ours — anchors allocated before the decision

second/                   the agent that debugs the agent. never imported by belay/
  evidence.py             pointers, deterministic fetch, coverage semantics
  dossier.py              untrusted Claim vs validated Dossier; query vs completion
  adjudicate.py           the pipeline, the validator, and the trusting control
  apply.py                dossier to durable record; authorisation at execution

services/
  ledger.py               the oracle; what actually committed
  payments.py             three tiers: idempotent / queryable / opaque

experiments/
  harness.py              spawn, crash, recover, grade
  run_matrix.py           4 runtimes x 3 tiers x 5 crash points x 2 disciplines
  run_divergence.py       the mechanism, deterministically, with annotated journals
  run_revocation.py       invariant 2 under mid-flight permission changes
  run_adjudication.py     escalated anchors x evidence tiers x agent profiles
  build_evidence.py       materialises out-of-band records from the ledger
  analyze.py              produces every number quoted in FINDINGS.md

tests/test_contract.py    invariants asserted directly, under real SIGKILL
tests/test_second.py      the adjudicator's safety properties
viewer/build_viewer.py    generates a self-contained forensic readout
results/                  raw trial logs and findings.json  (committed on purpose)
```

## The recovery desk

The viewer now includes an evidence-guided recovery desk alongside the original
crash traces. Follow a halted refund through a rejected stale report, a covering
settlement report, and an actual resumed sandbox workflow. A separate case shows
permission being revoked after a recovery was proposed.

```bash
make recovery-demo
# Or, without make:
python3 experiments/recovery_demo.py
python3 viewer/build_viewer.py --demo-json tmp-runs/recovery-demo.json
```

Open `viewer/trace.html`, or serve the `viewer` directory with
`python3 -m http.server 8000 --bind 127.0.0.1 --directory viewer`.
The page is an interactive recording of real local crash experiments with
sandbox payments. Browsing a recording issues no payments or model requests.
Its default agent is a deterministic heuristic; an optional OpenAI adapter can
generate a recording with a real model. The model only proposes evidence and a
claim, and every claim still passes through the deterministic validator.

See **[the demo guide](docs/DEMO.md)** for live-model setup, the bounded evaluation,
a 60-second presentation script, and downloadable CI artifacts. No live-model
performance or production savings are implied by the recorded simulator results.

## The trace viewer

`make viewer` writes a single self-contained HTML file — no build step, no
network, no assets. Five scenarios, four runtime lanes each, with the crash
marked as a hard seam and the money figure per lane:

```
  lost ack, cooperative │ lost ack, opaque │ diverged decision │ books wrong │ scope revoked
  ─────────────────────────────────────────────────────────────────────────────────────────
  naive             ○ decided  ○ intent  ╎  ○ decided  ○ intent  ● settled        $100.00
                                         ╎                                   +$50.00 vs order
  replay_position   ○ step     ● refund  ╎  ○ step     ● refund                   $100.00
  replay_content    ○ step     ● refund  ╎  ○ step     ● refund                   $100.00
  anchored          ⊙ anchor   ⊙ anchor  ╎  ◐ resolved  ⊘ escalated                $50.00
                    ○ intent             ╎                                         escalated
                                         ╎
                        process died ────╯
```

Hovering any record shows its journal payload. The lane names, the seam, and
one number per lane are the whole design: it is meant to be legible in a
screen recording without narration.

## Why you should care

Teams operating agents that issue refunds, orders, or provisioning requests
must handle uncertain external outcomes. Persisting model decisions and using
stable action identifiers is a sound approach with a cooperative service;
durable workflow systems support that discipline. Belay explores enforcing
effect identity, current authorization, and evidence requirements explicitly,
including when a service cannot resolve an ambiguous outcome.

The benchmark compares the recovery semantics implemented in this repository.
It is not a measurement of Temporal, LangGraph, or another deployed framework,
and simulated loss rates are not estimates of production loss rates.
