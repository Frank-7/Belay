# Belay project documents

Belay now has two complementary local products. The investor pitch leads with
the Payment Mission MVP: a plain-language request becomes an exact reviewed
authorization, simulated payment and linked receipt. The Recovery Desk handles
the different problem of investigating an interrupted action whose outcome is
uncertain. Distinguish both from recorded demonstrations and future live
financial integrations.

| Document | Status | Purpose |
|---|---|---|
| [Payment Mission MVP](PURCHASE_SIMULATOR.md) | Current runnable investor product | Open-ended request composer, reviewed authority, simulated payment, backend audit and scoped receipt |
| [Mission presentation](MVP_PRESENTATION.md) | Current pitch | Three-minute walkthrough, 60-second pitch and investor questions |
| [Integration guide](INTEGRATION.md) | Current implementation boundaries | Run both local products and understand their separate state, authority and evidence paths |
| [Legacy purchase recovery bridge](PURCHASE_SIMULATOR.md#legacy-v03-recovery-bridge) | Implemented compatibility path | Durable pre-dispatch uncertainty and typed, read-only payout investigation for `belay.purchase.v0.3` |
| [PR #10 integration record](PR10_PAYMENT_REVIEW.md) | Merged Recovery Desk review | Reusable recovery components, resolved lifecycle finding and remaining payment-adapter boundaries |
| [Test-wallet setup](TEST_WALLET.md) | Human-signed test-network demo | Configure MetaMask, obtain test tokens and understand Arc receipt verification |
| [Final Recovery Desk presentation](FINAL_PRESENTATION.md) | Prepared supporting pitch | Recovery-focused script, judge questions and buyer questions |
| [Next stage](NEXT_STAGE.md) | Current execution plan | Harden the pitch, connect one real payment domain and reuse Recovery Desk safely |
| [Checkpoints](CHECKPOINTS.md) | Submission plan | Recording buffers, milestones and evidence discipline |
| [Public website](WEBSITE.md) | GitHub Pages | Build and publish the static introduction and recorded walkthroughs |
| [Repository review](REVIEW.md) | Updated findings | Fixed runtime defects, evidence checks and remaining production limits |
| [Recovery Desk and evaluation](DEMO.md) | Recorded demo and bounded comparison | Inspect crash recordings and run the optional model evaluation |
| [Evidence adjudicator](SECOND.md) | Research foundation | Validate evidence for ambiguous actions; not a payment or claims authority |
| [Recovery Lab](PROTOTYPE.md) | Legacy local simulation | Earlier separate SQLite prototype retained for baseline comparison |
| [Autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md) | Broader production architecture | Advance delegation, protected execution and connected services |
| [USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md) | Proposed live payment plan | Base grants, USD payee payouts, fund locations and recovery boundaries |
| [Internal payment protocol](INTERNAL_PAYMENT_PROTOCOL.md) | Proposed service contract | Backend API roles and mapping to guarded payment actions |
| [MVP master plan](MVP_MASTER_PLAN.md) | Ticket-focused architecture foundation | Payment, evidence, reserve-backed remedies, partners and acceptance tests |
| [Subscription and guarantee proposal](SUBSCRIPTION_GUARANTEE.md) | Future internal proposal | Potential terms and remedies; no active subscription or funded guarantee |
| [Recovery and guarantee decision](RECOVERY_AND_GUARANTEE_DECISION.md) | Earlier architecture decision | Payment rails, recovery and possible future loss protection |
| [Concert blueprint](CONCERT_APP_BLUEPRINT.md) | Deferred vertical design | Ticketing research retained as one future domain adapter |
| [AP2 learnings](AP2_PODCAST_LEARNINGS.md) | Research notes | Protocol roles, signing and adoption boundaries |
| [Stripe learnings](STRIPE_COMMERCE_LEARNINGS.md) | Research notes | Payment options and integration constraints |
| [Earlier card protocol](PAYMENT_PROTOCOL_CARD_REFERENCE.md) | Superseded design | Preserved card-settlement comparison |
| [Earlier merchant-wallet design](USDC_ESCROW_REFERENCE.md) | Superseded v0.2 design | Historical contract escrow and merchant conversion assumptions |

The Payment Mission MVP shapes invoices, bills, premiums, taxes,
subscriptions, transfers, tickets and other purchases, but does not execute
those real services. Its model, money and provider edges are simulated. The
legacy `belay.purchase.v0.3` ticket path now uses a deterministic Recovery Desk
evidence bridge for its fictional lost-payout case. The generalized
`belay.mission.v0.1` path still needs its own typed recovery adapter. Recovery
Desk can use an optional model to propose evidence interpretations; it cannot
sign or autonomously send its Arc Testnet wallet transfer. The repository
offers no guarantee, insurance, reimbursement, tax filing, bank connection,
production USDC conversion or live purchasing integration. Research outcomes
are controlled measurements, not customer loss rates.
