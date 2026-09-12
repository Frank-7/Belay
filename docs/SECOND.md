# The second

**Closing the escalation hole without opening a worse one.**

In climbing, the *second* belays the leader, then follows the route and
inspects every piece of protection the leader left behind. They never lead,
and they never place the gear the rope hangs on.

---

## 1. The hole

`anchored` halts on an anchor it cannot resolve. That is invariant I3 and it
is the honest thing to do — but on the `opaque` tier it is also a dead end.
A human is handed a hex string and a reason, and the workflow stays down
until they work out what happened. FINDINGS.md §5 measures the cost: an
escalation rate of 0% on any service offering idempotency or a lookup,
rising to 60% on a service offering neither.

CONTRACT.md §4 proves no runtime can do better. It is worth being precise
about what that proof says, because the scope is narrower than it first
reads:

> Given only the journal and the service API, from inside the process, a
> lost acknowledgement on an `opaque` service is undecidable.

Every clause is load-bearing. The proof is about what is *decidable from
inside the process*. It is not a proof that the fact is unknowable. The
outside world keeps other records — settlement reports, webhook archives,
statements, support tickets — and a fact absent from the service API may
well be present in one of them.

So this package does not weaken the contract. It widens the input.

## 2. Why an agent, and why it cannot be trusted

Finding the right record is a search problem over heterogeneous systems with
no schema in common, which is the kind of thing a model is good at. Deciding
whether a record *settles the question* is a correctness problem about
money, which is the kind of thing a model is bad at, and worse, is bad at
fluently.

The failure mode is specific and it is not exotic. Ask a model "did this
refund go through?", give it a settlement report, and if the report is
silent it will tell you the refund never happened. That inference is wrong
whenever the report's coverage window does not extend past the moment the
call was attempted, and it is wrong in the expensive direction: acting on it
issues the refund a second time. "I looked and found nothing" reads as
evidence and is not.

Which lands us in the same shape as the rest of the repo. A nondeterministic
component cannot be allowed to own an outcome that money depends on. The
resolution is the same too: constrain what the component is permitted to
produce, and verify all of it.

## 3. The three rules

**1. The import direction is the guarantee.**
Nothing under `belay/` imports `second/`, and nothing under `second/`
imports `services/ledger.py`. The first keeps a nondeterministic component
out of the recovery path, which would otherwise reintroduce exactly the bug
this project exists to describe. The second keeps the adjudicator away from
the grading oracle, without which every number below would be worthless.
`tests/test_second.py` asserts both by parsing the source.

**2. The agent produces pointers, a three-way verdict, and prose. Nothing else.**
It never names an anchor, an amount, a scope, or an external id — those come
from the journaled intent. A *pointer* is fetched deterministically by
`EvidenceStore`, so a fabricated one resolves to nothing and cannot be
cited. A *verdict* is checked against the observations actually fetched, so
an unsupported one is forced to abstain. *Prose* is for the human and is
load-bearing for nobody.

This is `anchored.py` rule 1 one level up. The model chooses where to look;
it does not get to invent effect identities.

**3. Evidence enters as a query result, never as a conclusion.**
What gets fsynced is the retrieved artefact's digest and provenance, not the
agent's summary of it. `anchored.State` projects that record exactly as it
projects a `resolved` record from the reconciliation ladder, because that is
what it is: the ladder grew a rung that happens to read files instead of
calling an API.

## 4. Coverage, and the asymmetry that falls out

Every evidence source declares what it knows about its own completeness.

| coverage | a hit means | silence means |
|---|---|---|
| `complete_until(t)` | the effect committed | the effect did not commit, **if** the attempt was at or before `t` |
| `lossy(p)` | the effect committed | nothing, at any `p > 0` |

Any source can prove an effect *happened*. Only a source claiming
completeness over the window containing the attempt can prove one *did not*.
That asymmetry is not a modelling convenience — it is why a webhook archive
can close some anchors and never close others, and it accounts for most of
the abstentions in §6.

Establishing absence therefore requires two citations from the same source:
the manifest that claims the coverage, and the silent query. Citing the
silence alone is the mistake in §2, and the validator rejects it.

## 5. The ladder, extended

`belay/runtimes/base.py` has two rungs. The adjudicator adds a third and a
fourth, and the split between them is the same one that caused the bug in
FINDINGS.md §6.

```
rung 1  query the service          creates nothing · no permission needed
rung 2  complete via the service   new effect      · live permission required
        ── service is opaque; the runtime halts here ──
rung 3  query out-of-band records  creates nothing · no permission needed
rung 4  complete, evidence having  new effect      · live permission required
        proved the effect absent
```

Rung 4 is checked against the permission store microseconds before it acts,
inside `apply_dossier`. A dossier may sit in a queue for an hour while a
human reads it, so it cannot carry an authorisation with it — I2 says the
check and the call must not be separated by a restart.

**Rung 4 anchors its own effect before issuing it.** It fsyncs an
`adjudication_intent` record first, for precisely the reason the runtime
fsyncs an intent first: a crash in the window would otherwise let a *later*
adjudication read a stale report, see silence, and conclude absence a second
time. `escalated_slots` folds that timestamp into the coverage requirement.
The tool built to close the escalation hole turns out to be subject to the
discipline it was built to serve, which is either pleasing or embarrassing
depending on how long it took to notice.

## 6. Results

400 adjudications of anchors that `anchored` really halted on, after a real
SIGKILL on the `opaque` tier. Graded against the ledger, never against the
adjudicator's report. Reproduce with `make adjudication`.

Two crash points, chosen because they are the two halves of the ambiguity
and the ledger disagrees about them: `in_flight` (the refund committed, the
caller never saw the ack) and `after_intent` (the intent is durable, no call
was ever made). Indistinguishable from inside the process.

**The headline.** Both columns run the same agents over the same evidence.
The only difference is `validate`.

| pipeline | cases | closed | abstained | **false** | duplicate refunds | overpaid |
|---|---|---|---|---|---|---|
| `trusting` | 200 | 108 | 79 | **13** | 7 | $210 |
| `validated` | 200 | 90 | 110 | **0** | 0 | $0 |

The 13 false resolutions split into the two failure modes this repo already
has names for. Seven are **duplicate refunds** — the agent read a report
whose cutoff preceded the attempt, concluded absence, and paid twice (I1).
Six are **books wrong** — the agent asserted commitment citing a digest
nobody produced, the anchor closed, and the ledger holds nothing, so the
operator is told the refund went out when nothing did and no alert fires
(I4).

**What is knowable, by evidence tier** (validated pipeline):

| evidence tier | cases | closed | abstained | false |
|---|---|---|---|---|
| `none` | 40 | 0 | 40 | 0 |
| `webhook_only` | 40 | 18 | 22 | 0 |
| `stale_settlement` | 40 | 0 | 40 | 0 |
| `settlement` | 40 | 35 | 5 | 0 |
| `both` | 40 | 37 | 3 | 0 |

`none` is the hole exactly as it stands, and the adjudicator correctly leaves
it exactly as it stands. `stale_settlement` is the interesting row: a report
that is perfectly truthful and completely uninformative about the window in
question. The validated pipeline closes nothing there, because nothing
vouches for the silence.

The trusting pipeline does close cases on that tier, and it cannot do
otherwise. The only thing distinguishing a stale report from a complete one
is a coverage claim, and a pipeline that never checks coverage cannot see
the difference — both look like a report it searched and found nothing in.
Whether a given closure turns out to be right is then settled by whether the
effect happened to commit, which is luck rather than evidence. Some are
correct, and that is exactly the problem: an adjudicator can be right for no
reason, and a rate of being right for no reason is not a safety property.

**How badly the model behaves** (validated pipeline, covering reports only,
where everything is in principle knowable):

| profile | closed | abstained |
|---|---|---|
| `competent` | 16 / 16 | 0 |
| `hallucinating` | 16 / 16 | 0 |
| `overconfident` | 16 / 16 | 0 |
| `lazy` | 12 / 16 | 4 |
| `adversarial` | 12 / 16 | 4 |

This is the shape worth reading twice. **A bad agent costs availability, not
correctness.** Hallucination is free — a fabricated pointer resolves to
nothing, at a cost of one to two wasted fetches per case and no change in
outcome. Overconfidence is free — 42 unsupported verdicts were rejected
across the run, and every one became an abstention. Only laziness costs anything real:
an agent that never asks what a source covers cannot establish absence, so
it leaves anchors halted that were resolvable. It is never *wrong* about
them.

All 90 closed anchors resumed to a committed workflow report, which is the
narrow claim of this package: the halt is no longer a dead end.

### On run-to-run variance

Both agents here draw fresh entropy per process, so most of the figures
above are sample statistics and will move when you re-run. What moves: the
trusting control's false count and its split into duplicates and books
wrong; the overpaid figure; every per-tier and per-profile close rate; the
wasted-pointer means. `make adjudication` overwrites them with a new draw.
Read them for magnitude and direction.

Two things do not move, and this section is about them rather than about the
rates.

**The validated pipeline's zero.** No draw of an agent's conclusion can
produce a citation that was never fetched, or a coverage claim a manifest
does not make. Zero false resolutions is a property of `validate`, in the
same way that `anchored`'s zero in FINDINGS.md §1 is a property of
anchoring rather than a measurement of one.

**The coverage asymmetry in §4.** `none` and `stale_settlement` resolve
nothing under validation in every draw, because no source in either tier
vouches for its own silence. `webhook_only` closes some anchors and can
never close all of them, because a lossy source confirms and never
exonerates. Those rows are entailments of the table in §4; measuring them
is a check on the implementation, not a discovery about the world.

The *direction* of the headline comparison is stable but not proved: the
control's false count varies and has not yet been zero across the runs we
have done. `experiments/check_docs.py` fails the run if it ever is, since a
control that makes no mistakes demonstrates nothing.

## 7. What this is not

- **Not a repeal of CONTRACT.md §4.** With no out-of-band records the
  adjudicator resolves nothing, which is the proof holding. What changed is
  that the input is no longer restricted to the journal and the service API.
- **Not exactly-once, still.** `validated` abstains on 110 of 200 cases.
  Those anchors stay halted and still need a human. The claim is that the
  halt is now the *floor* rather than the whole outcome.
- **Not a claim that a real model behaves like `DebugAgent`.** The simulator
  is parameterised by its vices precisely so the result does not depend on
  the model being good. What transfers is the pipeline; substituting a real
  model touches `propose_pointers` and `conclude` and nothing else. The
  measured resolution rate would move. The false-resolution rate is
  structural.
- **Not safe for multiple refund slots on one order.** On the `opaque` tier
  the service received no caller key, so out-of-band records match on order
  and amount, not on anchor. This workflow has one refund slot per order.
  Two slots would need distinct amounts, or a source carrying the client
  reference — which is to say a service that was `queryable` after all. The
  validator requires the amount to match the journaled intent and abstains
  otherwise; it does not paper over this.
- **Not a review of whether the refund was a good idea.** Same limit as the
  rest of the repo: execution and authorisation are in scope, and the
  quality of the decision is not.

## 8. Map

```
second/
  __init__.py      the import-direction rule, stated before any code
  evidence.py      pointers, deterministic fetch, coverage semantics
  dossier.py       Claim (untrusted) vs Dossier (validated); the typed
                   query/completion split
  adjudicate.py    the pipeline, the validator, and the trusting control
  apply.py         dossier to durable record; authz at execution time

experiments/
  build_evidence.py     materialises evidence artefacts from the ledger
  run_adjudication.py   400 cases: 5 evidence tiers x 5 agent profiles
                        x 2 pipelines

tests/test_second.py    37 assertions on the safety properties
results/adjudication.json
```
