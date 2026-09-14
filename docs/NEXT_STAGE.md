# Next stage: one useful AI Apps recovery platform

Belay remains in **AI Apps**. Keep one value proposition:

> Help an operator determine what an interrupted agent action actually did,
> and what can safely happen next.

Recovery Desk is the primary application. The Purchase Simulator is its
commerce use case: a customer can fund USDC while a merchant accepts USD through
a conversion/payout provider. The current purchase flow is fictional; it does
not establish custody, real USD settlement or funded customer protection.

## Implemented integration

The local Recovery Desk combines persistent incidents, research journals,
evidence explanations, deterministic contradiction checks, current permission
checks and guarded receipts. Its six cases cover lost acknowledgment,
unsubmitted refund, stale evidence, conflicting sources, revoked permission
and missing evidence. An optional OpenAI proposer remains separate from the
validator and executor.

The Purchase Simulator now calls the typed deterministic Recovery Desk
investigator for uncertain payouts. Original operation, mission, order,
beneficiary, exact intent, USDC base units and USD cents remain explicit.
Investigation reads evidence only. Its executor checks the current source
revision and fresh provider snapshot before recording an existing payout once.
Payment, delivery, supplier recovery and reserve reimbursement are separate.

The PR review fixes are implemented:

- An exact finalized Arc revert can close as a failed transfer without sending.
  A separate transfer still needs a new intent and explicit MetaMask signature.
- The purchase application persists dispatch uncertainty before provider I/O.
  A crash, expired quote/grant or later cancellation cannot free a possibly
  accepted hold. Missing evidence remains unknown and never triggers a retry.
- Auto play stops at uncertainty while explicit investigation/reconciliation
  stays usable. Both applications and research checks remain part of the
  integrated build; the shared documentation keeps their boundaries clear.

The original seven conflicts were in CI, `.gitignore`, Makefile, README,
`docs/INDEX.md`, `docs/INTEGRATION.md` and this file. The
[historical payment review](PR10_PAYMENT_REVIEW.md) retains its original
reproduction; those historical findings are not a statement that the current
fixes are still missing.

The 24-case evaluator reports precision, useful resolution coverage, refusal,
unknown handling, latency and model usage. The separate frozen 12-case boundary
suite is classification-only. Repeated published fixtures are regression
evidence, not new blind incidents. Historical `results/` and documented
measurement caveats remain intact.

## Complete the demonstration

| Priority | Completion criterion | Dependency or current limit |
|---|---|---|
| Operator journey | Create an incident, inspect evidence, resolve safely or explain what is missing, export the receipt. | Local implementation and offline regression coverage exist. |
| Commerce recovery | Show the USD-only merchant case, lose its payout reply, investigate and reconcile the original operation without another payout. | Provider, purchase and all reserve capital remain fixtures. |
| AI contribution | Compare the configured model with the heuristic on the same cases; report differences or no benefit. | Explicit model credentials/quota and a preserved configuration; no live-model run is claimed here. |
| Public testnet proof | A person signs a small Arc transfer and recovers its original outcome; retain the explorer link and test-money label. | MetaMask signature, faucet availability and network access; no actual transfer is claimed by offline tests. |
| Presentation | Record one 60-second AI Apps story with a difficult recovery decision and one measured next improvement. | Use the prepared script and correctly label recorded, simulated and actual testnet evidence. |

Use [FINAL_PRESENTATION.md](FINAL_PRESENTATION.md) for the main operator pitch
and [MVP_PRESENTATION.md](MVP_PRESENTATION.md) for the commerce scenario. Keep a
recording/upload buffer before the next confirmed deadline and freeze new
features before presenting. [CHECKPOINTS.md](CHECKPOINTS.md) preserves the
supplied schedule discrepancies. These documents do not claim that a video,
submission, organizer message or customer interview has been sent.

## Next external integration

Choose one merchant with an accepted USD payment method and one approved
customer-funded USDC conversion/payout route. Confirm the provider's sandbox
access, supported chain, beneficiary identity, operation idempotency, evidence
freshness and settlement finality before implementing against it.

**Provider sandbox work is deferred:** no provider account or credentials are
configured. Do not substitute an invented successful API call or use real
funds to complete this dependency. The local typed adapter and failure tests
are the contract for that future integration. Keep the working Arc Testnet
adapter until a separate chain/provider implementation is actually available.

The future Base grant/contract, restricted executor and conversion proposal is
preserved in [MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md),
[USDC_SETTLEMENT_ARCHITECTURE.md](USDC_SETTLEMENT_ARCHITECTURE.md) and
[INTERNAL_PAYMENT_PROTOCOL.md](INTERNAL_PAYMENT_PROTOCOL.md). Contract tests,
signer isolation, replacement/reorg handling and authenticated external
evidence are independent future requirements. There is no automatic Arc/Base
migration and no production isolation implied by Python module boundaries.

Live protection requires an identified payer, funded obligations, actual
eligibility terms and independent claim authority. Returning still-held funds,
recovering from a supplier and paying a new reserve remedy are different
actions. An unknown payout is not automatically an eligible loss. See
[SUBSCRIPTION_GUARANTEE.md](SUBSCRIPTION_GUARANTEE.md) and
[RECOVERY_AND_GUARANTEE_DECISION.md](RECOVERY_AND_GUARANTEE_DECISION.md).

## Validate the buyer and measurable value

The initial buyer hypothesis is a support-automation or financial-operations
team handling uncertain agent actions. A commerce operator is a concrete
adjacent test of the same need. Interviews remain a human task; the repository
does not establish demand, willingness to pay or customer incident rates.

Ask for a recent incident, the current workaround and the evidence needed
before authorizing another action. Use the questions in
[FINAL_PRESENTATION.md](FINAL_PRESENTATION.md). Compare a read-only shadow
pilot against the operator's existing process, including proper stable-key
retry and current permission checks. Measure useful resolutions, unsupported
conclusions, unresolved cases, investigation time, integration effort and
latency. A small sample cannot establish a rare-loss rate or guarantee price.

Defer a generic marketplace, broad merchant coverage, live ticket checkout,
subscription billing, custody, escrow and insurance until this recovery
workflow earns use. The earlier concert, delegation, card and merchant-wallet
documents remain research/proposals in [INDEX.md](INDEX.md). Preserve the
archived/partial Gemini experiments and each run's actual completion counts;
they do not measure the purchase planner or production error rates.
