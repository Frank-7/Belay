# Next stage

## Deliverable now

The repository contains the local Recovery Lab plus current architecture,
subscription/guarantee proposal and this execution plan. These documents do
not activate customer coverage, subscription billing or a payment integration.
Use [the index](INDEX.md) to distinguish implemented work from plans.

## First build increment

Keep concert tickets as the main example. Build a simulated purchase flow
that shares the Recovery Lab's durable-execution approach. One user grants
authority for exactly two adjacent seats within an inclusive USD 300 budget.
The agent selects an eligible USD 280 fixture offer, submits it, survives an
interruption and shows the original outcome without another routine approval.

Required pieces are a real model planning adapter, structured grant and quote,
deterministic validation, atomic budget reservation, a protected test signer,
simulated seller adapter, persisted operation and an activity screen.
Label test signatures and simulated money; do not claim production AP2
interoperability without implementing and checking the selected profile.

Done means: eligible work proceeds; wrong quantity, wrong event/date and
excessive cost are blocked; current authority is checked; restart recovers the
original action; an unknown outcome stays unknown. A correct provider-idempotent
baseline must be shown alongside Belay.

## Second build increment

Add a guarantee demonstration using fictional subscription entitlement and
claim amounts. Simulate a duplicate purchase that cannot be fully refunded.
Show its evidence, net loss, cap and proposed reimbursement. Also show a
correct purchase with buyer remorse and explain its different treatment.

Done means: the same loss cannot produce two payouts; previous refunds reduce
the eligible amount; terms version and remaining limits are visible; an
unknown purchase is not automatically treated as a loss. Actual claims remain
unavailable until the commercial and legal route is established.

## Commercial validation in parallel

| Work | Evidence required before advancing |
|---|---|
| Interview frequent delegators | A recent failed purchase/task, real impact and current workaround |
| Test the offer | Willingness to delegate and pay at a clearly disclosed cap; compare service-only and guarantee propositions |
| Confirm financial structure | Named payer, reviewed terms, funded obligations and approved launch scope |
| Confirm provider access | Supported booking/payment route and documented recovery guarantees |
| Observe a controlled pilot | Eligible actions, net losses, unresolved outcomes, support cost and repeat use |

Do not invent demand or broad market statistics from interviews that have not
happened. A small pilot can expose problems without proving a rare-loss rate.
Before expanding limits, test common-cause failures and delayed claims as
well as ordinary successful purchases.

## Expansion after the first working mission

Add one paid research mission using the same grants, budget ledger, executor
and evidence model. Use named sources for trends and traffic estimates.
Do not build an agent marketplace or support every merchant at once.

For the hackathon, target a complete demonstration by hour 48. The supplied
72-hour playbook conflicts with the stated 48-hour environment window.
If 72 hours is confirmed, use the remaining time for hardening and evaluation.
Prepare a repository link and 60-second progress video for each required
check-in; confirm the actual schedule with the organizers.

## Selected direction and remaining dependencies

- Use existing payment rails with cancellation/refund recovery. Blockchain is
  not a prerequisite for reversing an economic loss.
- Belay supplies the app and its service-fee remedy. Pursue a licensed partner
  for transaction-loss protection; no partner or policy is secured.
- Exact guarantee triggers, amount limits, price and initial live jurisdiction.
- Which merchant and autonomous payment integration grants access.

The architecture and simulator can proceed while these decisions are resolved.
Live financial promises depend on the payer, terms and permissions actually
being ready.

## Recent repository work to preserve

The main branch now includes a separate Gemini decision-stability experiment
and an evidence adjudicator under `second/`. The Gemini results preserve
separate archived and partial runs, including the earlier 150-response sample.
Inspect each run's configuration and completion counts before quoting its
results. These measurements do not establish a production error rate or
replace the proposed app planner.
The adjudicator evaluates evidence for research recovery; it is not a claims
operation or a funded reimbursement service. Preserve these additions when
integrating the Recovery Lab and current product documents.
