# Belay project documents

Read these in order. Product plans describe proposed work, not live capabilities.

| Document | Status | Purpose |
|---|---|---|
| [Public website](WEBSITE.md) | GitHub Pages site | Preview, build and publish the product introduction and recorded demo |
| [Payment Mission MVP](PURCHASE_SIMULATOR.md) | Current runnable investor product | Open-ended request composer, reviewed authority, simulated payment, backend audit and scoped receipt |
| [MVP presentation](MVP_PRESENTATION.md) | Current presentation plan | Three-minute walkthrough, 60-second pitch and judge questions |
| [MVP master plan](MVP_MASTER_PLAN.md) | Ticket-focused architecture foundation | Agent interactions, USD supplier payment, evidence, reserve-backed remedies, partners and acceptance tests |
| [PR #10 payment review](PR10_PAYMENT_REVIEW.md) | Teammate integration review | Verified main compatibility, one reproduced wallet lifecycle defect, reusable recovery components and remaining product layers |
| [Autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md) | Current product direction | Advance delegation, protected execution and connected services |
| [USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md) | Selected v0.3 payment plan | Base grants, USD supplier payouts, fund locations, protection reserve and recovery |
| [Internal payment protocol](INTERNAL_PAYMENT_PROTOCOL.md) | Proposed USDC implementation contract | Backend API roles and mapping to guarded contract actions |
| [Integration guide](INTEGRATION.md) | Repository boundaries and extension contract | How the existing runtime, adjudicator, lab and proposed services fit |
| [Subscription and guarantee proposal](SUBSCRIPTION_GUARANTEE.md) | Internal proposal only | Customer offer, potential remedies, loss prevention and economics |
| [Recovery and guarantee decision](RECOVERY_AND_GUARANTEE_DECISION.md) | Selected architecture | Refunds, blockchain limits and who should carry losses |
| [Next stage](NEXT_STAGE.md) | Build and validation plan | Deliverables, dependencies and acceptance criteria |
| [Recovery Lab](PROTOTYPE.md) | Implemented local simulation | Run the existing demonstration and understand its limits |
| [Recovery Desk and evaluation](DEMO.md) | Implemented recorded demo; optional model adapter | Inspect evidence-backed recovery and compare bounded recovery agents |
| [Repository review](REVIEW.md) | Known engineering findings | Unresolved research-runtime defects and evidence limits |
| [Evidence adjudicator](SECOND.md) | Existing research code on main | Validates evidence for ambiguous research actions; not a guarantee claims service |
| [Concert blueprint](CONCERT_APP_BLUEPRINT.md) | Earlier design | Ticketing research; its per-purchase approval policy is superseded |
| [AP2 learnings](AP2_PODCAST_LEARNINGS.md) | Research notes | Protocol roles, signing and adoption boundaries |
| [Stripe learnings](STRIPE_COMMERCE_LEARNINGS.md) | Research notes | Payment options and integration constraints |
| [Earlier card payment protocol](PAYMENT_PROTOCOL_CARD_REFERENCE.md) | Superseded design | Preserved comparison; Stripe/card settlement is not the selected product architecture |
| [Earlier USDC merchant-wallet design](USDC_ESCROW_REFERENCE.md) | Superseded v0.2 design | Historical contract escrow; supplier no longer needs a crypto wallet or its own conversion account |

The Payment Mission MVP can shape requests for invoices, bills, premiums,
taxes, subscriptions, transfers, tickets and other purchases. It does not
execute those real services. The runnable code does not include live billing,
tax filing, insurance coverage, subscriptions, claims, reimbursements, ticket
booking, bank connectivity, a deployed blockchain contract, USDC conversion,
AP2 integration or a connected purchasing model.
The optional model in the Recovery Desk proposes evidence and claims only.
No guarantee is offered by this repository. Its original experiment results
are synthetic research results, not customer loss rates or guarantee pricing data.
