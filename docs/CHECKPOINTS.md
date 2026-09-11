# Checkpoint plan

Five scored check-ins plus a final round, all judged on the same four
categories: Innovation & Creativity 30%, Technical Implementation 25%,
Business Value & Impact 25%, Presentation & Communication 20%. Check-in
scores are averaged and combined with the final. A missed check-in is a zero.

That structure, not the deadline, is what this plan optimises for.

> **Confirm with the organisers before Saturday.** The invite email says 72
> hours and five check-ins; the challenge briefs say Saturday 10:00 to Monday
> 12:00 (50 hours) with four progress checkpoints plus a final. Those are
> different clocks and a different number of scored rounds. Ask, in writing,
> and plan against the answer.

---

## The 60-second template

Reuse this shape every round. It maps onto the rubric in order, so a judge
scoring against the sheet hears each category where they expect it.

| seconds | beat | rubric category |
|---|---|---|
| 0–10 | **The stake.** One concrete irreversible action going wrong. | Business Value |
| 10–20 | **The claim.** One sentence, falsifiable. | Innovation |
| 20–40 | **The evidence.** Screen recording of the failure, then ours. Numbers on screen. | Technical Implementation |
| 40–50 | **What changed since last checkpoint.** | Presentation |
| 50–60 | **Next 12 hours**, named specifically. | Presentation |

Rules that matter more than the script:

- **Show the ledger, not the logs.** The money number is the evidence. Logs
  are what you cut when you run over.
- **Say the limitation out loud in every video.** Judges who have read the
  briefs are explicitly primed to distrust a polished demo with no stated
  limits. Twelve seconds of "here is what this does not show" reads as
  confidence, not weakness.
- **Never re-explain the problem after round 1.** Ten seconds of stake, then
  straight to what's new. Repeating the setup is the single most common way
  teams waste a scored minute.
- **One number per video.** Round 1 is `0/240 versus 78/240`. Don't stack five
  statistics; nobody retains them.

---

## Checkpoint 1 — Saturday 22:00

**Have working:** everything currently in the repo. Core result, four
runtimes, 960-trial matrix, contract, tests, viewer.

Shipping a complete result at checkpoint one is the whole strategy. Most
teams will show a scaffold and a plan.

**Script**

> An agent issues a refund. The process dies between the payment landing and
> the acknowledgement coming back. On restart, nothing says whether fifty
> dollars left.
>
> Durable execution frameworks fix this by replaying the workflow from a
> journal. That's sound only if the workflow is deterministic — and if
> there's a model in it, the decision *is* the control flow.
>
> Our claim: an idempotency key derived from a nondeterministic decision
> inherits that nondeterminism, and a key that isn't stable across restarts
> isn't an idempotency key.
>
> [screen: baseline double-refunds $80 on a $50 order]
> [screen: ours, one refund]
>
> 960 real SIGKILLs, graded against an external ledger. Content-keyed replay
> violates the contract 78 times out of 240. Ours, zero. The fix is two
> fsyncs in the right order — allocate effect identity before you call the
> model.
>
> What this doesn't show: a real model. Our agent is simulated, so we've
> measured the mechanism, not how often it fires. That's the next twelve
> hours.

---

## Checkpoint 2 — Sunday 10:00

**Build:** FINDINGS.md §8 item 1. Replace the simulated agent with a live
model call and measure the real divergence rate — how often the same prompt
yields a different decision — split by temperature and task ambiguity.

This is the novelty checkpoint. It converts an assumed parameter into a
measured one, and it is the thing a sceptical judge will ask about first.

**Script beats:** the divergence rate, as one number. Then: our whole result
is conditional on that rate being non-zero, so here is what it actually is.
State whether the rate held up or surprised you — a lower-than-expected rate
is still a finding and saying so buys credibility you cannot buy any other
way.

---

## Checkpoint 3 — Sunday 22:00

**Build:** FINDINGS.md §8 item 2, the largest gap. A lease so two processes
cannot recover the same journal, then extend invariant I1 to cover
concurrency and re-run the matrix with concurrent recoverers injected.

**Script beats:** name the assumption you have been carrying since round one
and show it removed. Judges reward a team that attacks its own weakest claim
unprompted.

---

## Checkpoint 4 — Monday 10:00

**Build:** pick exactly one.

- **Unbounded effect slots** (§8 item 3). Anchoring needs slots enumerated
  before the decision. What happens when the *number* of actions is itself
  model-chosen? Our hypothesis is a bounded slot pool with refusal on
  exhaustion. If it doesn't hold, say so — a negative result here is a
  stronger contribution than a feature.
- **Converting opaque to queryable** (§8 item 4). A write-ahead proxy that
  gives an uncooperative service a lookup. This moves the impossibility
  rather than removing it, and the trade should be measured.

Do not start both. A half-built second thing scores worse than one finished
thing at every checkpoint.

**Script beats:** the result, and explicitly whether it confirmed or broke
the hypothesis.

---

## Checkpoint 5 / Final — Monday 12:00

No new code. Consolidation only.

- Re-run `make all` clean and confirm every number in FINDINGS.md.
- Trim the limitations section to what is still true.
- Final video: the stake, the claim, the single strongest before/after, the
  headline number, and the one thing you would build next.

**Final-round script**

> Companies shipping agents that take irreversible actions — refunds,
> orders, provisioning — are wrapping them in durable-execution frameworks
> built on an assumption the agent violates. The failures are rare, silent,
> and financial.
>
> We showed why: a key derived from a model's decision isn't stable across a
> restart, so it isn't a key. We showed it costs real money — [N] dollars
> mis-moved across our matrix. We fixed it by allocating effect identity
> before the model is consulted, and proved the one case where nobody can
> win.
>
> Zero contract violations in [N] real process kills. Zero availability cost
> on any service that cooperates at all, and on services that don't, a
> proof that the escalation is necessary rather than conservative.
>
> The gap we'd close next: [whatever checkpoint 4 left open].

---

## Division of labour

| owner | scope |
|---|---|
| **Systems** | Runtime, journal, chaos injector, the lease at checkpoint 3. |
| **ML / research** | The agent, the live divergence measurement, the matrix and analysis. |
| **Product / frontend** | The viewer, and all six videos. |

The videos are one person's standing job from hour one. Six scored minutes
at 20% each is more rubric weight than any single technical feature, and a
team that films at the deadline loses that weight every round.

The viewer is the presentation multiplier: four lanes, a hard red seam where
the process died, and a money figure per lane. It makes the twenty-second
evidence beat work without narration. Keep it current at every checkpoint —
regenerating it is one command.
