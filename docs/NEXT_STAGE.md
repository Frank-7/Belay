# Next stage: one connected payment mission

Belay is competing in **AI Apps**. The current pitch has one product promise:

> Tell Belay what to pay. It turns the request into one exact authorization,
> executes under deterministic controls and keeps a receipt of what happened.

The Payment Mission MVP leads the demonstration. Recovery Desk remains the
implemented supporting product for an operation whose external outcome is
uncertain. The legacy `belay.purchase.v0.3` path now uses it through a typed,
read-only purchase investigation. The generalized `belay.mission.v0.1` path
still needs a domain-neutral observation adapter rather than another executor.

No interviews, willingness to pay, provider access or customer incident rates
are established by this repository.

## Implemented now

| Product | Working local path | Boundary |
|---|---|---|
| Payment Mission MVP | Open-ended request, editable plan, exact authorization, deterministic checks, simulated USDC hold and USD payout, scoped receipt, synchronized customer/backend views | No model, wallet, chain, bank, payee or real money is connected |
| Legacy v0.3 purchase recovery | Durable dispatch-attempt record, reserved hold, exact-operation investigation and evidence-bound reconciliation | Ticket fixture only; not connected to the universal mission interface |
| Recovery Desk | Persistent incidents, bounded optional model proposal, deterministic evidence validation, guarded operator resolution and audit export | Local refund fixture; no autonomous payment key or live remedy |
| Arc test wallet | Human-signed capped test-USDC transfer and read-only finalized-receipt verification | Arc Testnet only; separate from Payment Mission settlement |
| Research runtime | Anchored side-effect experiments and recorded crash demonstrations | Synthetic measurements; POSIX crash harness |

## Freeze for the investor pitch

1. Run one complete invoice mission from request through receipt.
2. Start one incomplete tax or insurance request and show that the payee,
   amount or required reference stays blank until supplied.
3. Keep the main interface in plain language. Use the technical audit only to
   answer questions about authority, money movement and retries.
4. Rehearse from a fresh `mission-v1` data directory and keep a local recording
   as a fallback.
5. Run the targeted Python and JavaScript suites, documentation consistency
   check and full repository lint before freezing the branch.

Do not add another customer scenario or visual mode during the pitch freeze.
The example prompts must exercise the same composer and state machine.

## First connected pilot

Choose one invoice or bill-payment provider with a documented sandbox. A
successful increment must replace one fictional edge end to end:

1. An authenticated user or agent submits a request without sending payment
   credentials to the model.
2. The planner returns a structured proposal; unknown payee, amount and
   reference fields remain unset.
3. The user reviews one exact payment and the authority service records the
   beneficiary, amount, purpose, operation identity and expiry.
4. A regulated provider accepts the fixed instruction, converts or sources the
   required funds and pays the verified USD destination.
5. Belay reconciles a lost or delayed response under the original operation
   identity before it permits any retry.
6. The invoice or biller adapter reports authoritative posting evidence, which
   the receipt distinguishes from payment-provider evidence.

Done means a controlled interruption after provider acceptance cannot create a
second payment, a stale browser action cannot alter the plan, and an empty
provider lookup remains unknown. A provider sandbox result is still not live
money or customer validation.

## Reuse Recovery Desk safely

PR #10 is merged. Its Recovery Desk, Arc verifier and finalized-failure
lifecycle are implemented; `250456f` closed the pre-merge failure dead end.
Commit `fe23651` applies the same read-only evidence boundary to the legacy
`belay.purchase.v0.3` payout-reply-lost path. It persists possible dispatch
before provider I/O, keeps the hold reserved, rejects missing or conflicting
evidence and reconciles the original paid operation only after a fresh provider
read.

Reuse that pattern for `belay.mission.v0.1` through a new domain-neutral
provider-observation interface:

- send the exact Payment Mission operation and provider identities;
- request read-only evidence and preserve unknown outcomes;
- return a typed observation with source, freshness, coverage and meaning;
- require the current Payment Mission authority before any new effect; and
- keep purchase, provider refund and any claim payout as separate operations.

Do not give the recovery model a wallet, signing callback or unrestricted
payment callback. Do not treat the human-signed Arc test transfer as the
USDC-to-USD settlement adapter. Arc and a future Base or provider route have
different chain, token and finality rules.

## Production gates

Before real funds, demonstrate:

- authenticated users and reviewed beneficiary onboarding;
- production signing and key custody outside the model;
- concurrent budget reservation and grant conservation;
- expiry, revocation and signature-replay ordering;
- provider idempotency lifetime and unknown-outcome reconciliation;
- late returns, duplicate callbacks and transaction replacement;
- payee-evidence identity, integrity, freshness and completeness;
- monitoring, audit export and operational escalation; and
- reviewed custody, money-transmission, tax, privacy and sanctions obligations.

A guarantee or reimbursement requires separate terms, decision authority and
funded capital. The payment agent cannot approve its own claim. Do not call the
product insured or promise automatic recovery until those roles exist.

## Validate the business problem

Interview financial-operations, support-automation or payment teams. Capture:

1. one recent agent or payment failure;
2. the evidence needed before an operator would retry or close it;
3. the current investigation time and escalation path; and
4. whether a reviewed payment plan plus linked receipt would change adoption.

Start with a shadow pilot that cannot issue live actions. Track completed
plans, missing facts, blocked authorizations, unknown outcomes, unsupported
conclusions, operator time, integration effort and added latency. A small
sample cannot establish a rare-loss rate, market size or guarantee price.

Use the buyer questions in [FINAL_PRESENTATION.md](FINAL_PRESENTATION.md) for
the recovery side and the investor questions in
[MVP_PRESENTATION.md](MVP_PRESENTATION.md) for Payment Mission.

## Defer until one domain works

Defer broad merchant coverage, recurring mandates, tax calculation or filing,
insurance coverage decisions, autonomous custody, escrow and a paid guarantee.
Tickets remain a useful future domain adapter in
[CONCERT_APP_BLUEPRINT.md](CONCERT_APP_BLUEPRINT.md), but the current interface
must continue to use one universal mission flow.

The supplied schedules disagree. Until the organizer confirms a deadline, keep
the conservative recording and upload buffers in
[CHECKPOINTS.md](CHECKPOINTS.md). This document does not assert that a
submission, customer interview or provider agreement has occurred.
