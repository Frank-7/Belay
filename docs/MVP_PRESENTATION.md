# Belay investor presentation

Use the runnable Payment Mission MVP on port 8777. All wallets, signatures,
USDC, conversion, USD payout and payee confirmation are local fixtures. The
product interaction, HTTP API, persisted workflow, revision checks and ledger
are implemented. General payment missions and the preserved ticket walkthrough
use distinct typed adapters over Recovery Desk's shared read-only payment
validator. The main demo includes a lost payout reply, evidence investigation
and explicit reconciliation under the original operation identity.

## One sentence

Belay makes an agent's proposed payment reviewable, then helps explain and
safely recover its outcome when the confirmation is lost.

## 60-second pitch

"People will ask AI to pay invoices, insurance, taxes, bills and purchases.
The payment API is the easy part. The dangerous part is letting an uncertain
AI choose who gets paid, how much and whether it should retry after a failure.

Belay is the control layer between the AI and the money. Give it a payment
request and it prepares a plan. Missing payees, amounts and required references
stay blank until the customer supplies them. One approval fixes the exact
beneficiary, amount, purpose and operation identity.

From there, deterministic controls take over. Belay checks the grant, reserves
the exact funds once, locks the instruction, pays through one stable operation
and investigates a lost reply before anyone retries. The operator inspects
the original payment evidence and explicitly reconciles it without sending
again. A linked receipt says exactly what happened. A tax receipt does not
pretend a return was filed. An insurance receipt does not pretend coverage was
approved.

The MVP beside me runs that complete flow with persisted state and simulated
USDC-to-USD settlement. We are building the payment-control contract that any
agent, wallet and regulated settlement provider can plug into."

## Live walkthrough

1. Type `Pay invoice INV-1042 for $1,250 to Acme Design by September 30`.
2. Enable **Simulate a lost payout reply**, then select **Prepare payment**.
   Point to the editable plan: this deterministic proposal is visible and has
   no authority yet. A live model is a separate integration.
3. Select **Authorize one payment**. Point to the fixed amount, beneficiary and
   one-time scope.
4. Let the payment run. Follow the customer progress on the left and the same
   event in **Behind this action** on the right.
5. Investigate the uncertain payout. Show exact intent and provider checks,
   then explicitly reconcile the original payment. Open the receipt and show
   the provider attempt count is still one, with honest confirmation scope.
6. Begin `Pay my federal estimated tax`. The missing amount and reference stay
   blank. Say: "Belay asks; it does not guess with money."

## What the prototype proves

- One interface can shape invoices, bills, insurance premiums, taxes,
  subscriptions, transfers, tickets and other purchases.
- The agent proposes; the user authorizes; deterministic code moves value.
- A stable operation identity and unique ledger keys stop a stale or repeated
  browser action from creating another local movement.
- The customer and backend views cannot tell different stories because both
  are rendered from the same persisted event.
- Receipt wording separates payment from external outcomes such as delivery,
  tax filing, remaining bill balance, coverage or claim approval.
- Both payment domains investigate the original operation through shared
  read-only evidence checks. The mission path preserves in-transit funds while
  uncertain, then accounts a confirmed payout after explicit fresh-evidence
  reconciliation. The older `/purchase/` walkthrough also preserves its
  pre-dispatch uncertainty and delivery/claim scenarios.

## What comes next

Replace each fictional edge with an approved adapter while keeping the same
control contract:

1. Connect an authenticated agent or planner to propose structured plans.
2. Connect a production wallet or custodian for USDC authority and holds.
3. Connect one regulated conversion and USD payout provider.
4. Verify one payee domain end to end, starting with an invoice or biller API.
5. Add provider reconciliation, production signing, compliance controls and
   operational monitoring.

## Questions investors may ask

| Question | Clear answer |
|---|---|
| Does it move real money today? | No. The current product is a local, durable simulation. Real settlement requires custody, compliance and provider contracts. |
| Is the AI in the demo? | No external model is connected. A deterministic local extractor shapes the request, and the interface is ready for a model adapter. |
| Can it calculate or file taxes? | No. It can prepare and simulate an exact tax payment. Calculation and filing require authoritative tax integrations. |
| Does an insurance payment prove coverage? | No. It proves only the simulated premium payment. Coverage and claims require the insurer's evidence. |
| Why use USDC if the payee wants dollars? | USDC is the internal source asset in the proposed architecture; a regulated provider converts it and pays verified USD details. The demo simulates that route. |
| Why will a merchant integrate? | The merchant can keep receiving USD. Belay's initial adapter target should use an existing invoice or bill-payment interface rather than require the merchant to adopt a wallet. |
| What if the payout provider's reply is lost? | The mission UI pauses, investigates the original payment through Recovery Desk's read-only validator, and requires explicit reconciliation with fresh matching evidence. Missing or contradictory evidence cannot authorize another send. |
| What is defensible? | The durable authorization and evidence graph across agents, wallets, payout providers and payee systems, plus the operational data required to reconcile failures safely. |
| Is it a blockchain or payment processor? | It is the control layer. Wallet, chain and settlement providers remain replaceable adapters. |
| What has actually been built? | A composer, editable plan, exact authorization, deterministic checks, simulated settlement, typed read-only investigation, explicit reconciliation, scoped receipt, synchronized audit and SQLite state; the older purchase walkthrough remains accessible. |

## Language for the pitch

Say **simulated settlement**, **reviewed authorization**, **one-time payment**,
**stable operation identity**, **linked receipt** and **provider adapter**.
Avoid claims such as *fraud-proof*, *insured*, *files taxes*, *proves coverage*,
*reverses a blockchain payment* or *works with every bank and merchant*.

The runnable product and production seams are documented in
[PURCHASE_SIMULATOR.md](PURCHASE_SIMULATOR.md). The earlier ticket-specific
design remains in [MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md) as architecture
research.
