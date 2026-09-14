# Belay project documents

Belay's fixed AI Apps direction is an operator application for recovering
uncertain agent actions. Start with **Recovery Desk on port 8766**. The
**Purchase Simulator on port 8777** demonstrates the commerce use case and
reuses its typed read-only investigator. Each app retains its own state.

| Document | Status | Purpose |
|---|---|---|
| [Integration guide](INTEGRATION.md) | Current implementation boundaries | Run both apps; understand journal, typed purchase evidence, execution and test-wallet boundaries. |
| [Test-wallet setup](TEST_WALLET.md) | Human-signed Arc Testnet integration | Obtain free test tokens and verify successful or reverted transfer evidence. |
| [Purchase Simulator](PURCHASE_SIMULATOR.md) | Implemented local commerce simulation | Bounded ticket purchases, fictional USD merchant payouts, delivery, reserve remedies and original-operation recovery. |
| [Next stage](NEXT_STAGE.md) | Current AI Apps execution plan | Implemented review fixes, remaining live demo dependencies and business validation. |
| [Final presentation](FINAL_PRESENTATION.md) | Prepared AI Apps pitch and questions | Operator story, judge Q&A and buyer questions; no claim that outreach occurred. |
| [Checkpoints](CHECKPOINTS.md) | Submission plan | Recording buffers, deadline caveats and evidence discipline. |
| [Repository review](REVIEW.md) | Engineering findings | Fixed runtime defects, bounded evidence checks and remaining research/production limitations. |
| [PR #10 payment review](PR10_PAYMENT_REVIEW.md) | Historical review with current status banner | Reproduced reverted-transfer defect, now fixed; original seven-conflict integration assessment retained. |
| [Public website](WEBSITE.md) | GitHub Pages | Build the static introduction and recordings; it does not host the Python services. |
| [Recovery Desk and evaluation](DEMO.md) | Recorded research demo and bounded comparison | Inspect crash recordings and run the optional model evaluation. |
| [Evidence adjudicator](SECOND.md) | Research foundation | Evidence-based research recovery; not authority to make purchases or pay claims. |
| [Recovery Lab](PROTOTYPE.md) | Legacy local simulation | Earlier separate SQLite prototype retained for baseline comparison. |
| [MVP master plan](MVP_MASTER_PLAN.md) | Future commerce specification, partially simulated | Agent roles, USD supplier payment, evidence, partners and separate funded remedies. |
| [MVP presentation](MVP_PRESENTATION.md) | Commerce scenario script | Present the fictional purchase use case within the AI Apps recovery story. |
| [Autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md) | Future architecture | Advance delegation and protected purchasing; no deployed autonomous spender. |
| [USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md) | Future Base/provider proposal | Bounded grants, USD supplier payouts, separate fund locations and protection; Arc remains the implemented test adapter. |
| [Internal payment protocol](INTERNAL_PAYMENT_PROTOCOL.md) | Proposed interfaces | Backend roles and contract/provider boundaries; no live `/internal/v1` service. |
| [Subscription and guarantee proposal](SUBSCRIPTION_GUARANTEE.md) | Internal proposal only | Potential customer terms and economics; no active subscription or funded guarantee. |
| [Recovery and guarantee decision](RECOVERY_AND_GUARANTEE_DECISION.md) | Earlier architecture decision | Payment rails, recovery and possible future loss protection. |
| [Concert blueprint](CONCERT_APP_BLUEPRINT.md) | Earlier design research | Ticketing ideas; the simulator implements only its labeled fictional scenario. |
| [AP2 learnings](AP2_PODCAST_LEARNINGS.md) | Research notes | Protocol roles, signing and adoption boundaries. |
| [Stripe learnings](STRIPE_COMMERCE_LEARNINGS.md) | Research notes | Payment options and integration constraints. |
| [Earlier card payment protocol](PAYMENT_PROTOCOL_CARD_REFERENCE.md) | Superseded commerce proposal | Preserved card/Stripe comparison; not the selected future USDC route. |
| [Earlier USDC merchant-wallet design](USDC_ESCROW_REFERENCE.md) | Superseded v0.2 proposal | Historical escrow design; the proposed USD merchant route requires no merchant crypto wallet. |

The real wallet integration is human-signed Arc Testnet. Belay stores no
private key and cannot autonomously spend from it. Purchase balances, claims,
reimbursements and reserve capital are implemented **only as fictional local
accounting**. No bank connection, live ticket booking, funded protection,
insurance or production purchasing planner exists. Research results remain
controlled measurements, not customer loss rates or guarantee pricing data.
