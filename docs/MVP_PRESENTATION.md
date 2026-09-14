# Belay investor presentation

Use the runnable Payment Mission MVP on port 8777. All wallets, signatures,
USDC, conversion, USD payout and payee confirmation are local fixtures. The
product interaction, HTTP API, persisted workflow, revision checks and ledger
are implemented.

## One sentence

Belay turns any payment request into one exact, reviewable authorization and a
payment trail an AI cannot silently rewrite.

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
and creates a receipt that says exactly what happened. A tax receipt does not
pretend a return was filed. An insurance receipt does not pretend coverage was
approved.

The MVP beside me runs that complete flow with persisted state and simulated
USDC-to-USD settlement. We are building the payment-control contract that any
agent, wallet and regulated settlement provider can plug into."

## Live walkthrough

1. Type `Pay invoice INV-1042 for $1,250 to Acme Design by September 30`.
2. Select **Prepare payment**. Point to the editable plan: the AI proposal is
   visible and has no authority yet.
3. Select **Authorize one payment**. Point to the fixed amount, beneficiary and
   one-time scope.
4. Let the payment run. Follow the customer progress on the left and the same
   event in **Behind this action** on the right.
5. Open the receipt. Show the linked request, authorization, provider result
   and honest confirmation scope.
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
| What is defensible? | The durable authorization and evidence graph across agents, wallets, payout providers and payee systems, plus the operational data required to reconcile failures safely. |
| Is it a blockchain or payment processor? | It is the control layer. Wallet, chain and settlement providers remain replaceable adapters. |
| What has actually been built? | An open-ended composer, editable plan, exact authorization, deterministic checks, simulated settlement, scoped receipt, two-sided audit, HTTP API and persisted SQLite state. |

## Language for the pitch

Say **simulated settlement**, **reviewed authorization**, **one-time payment**,
**stable operation identity**, **linked receipt** and **provider adapter**.
Avoid claims such as *fraud-proof*, *insured*, *files taxes*, *proves coverage*,
*reverses a blockchain payment* or *works with every bank and merchant*.

The runnable product and production seams are documented in
[PURCHASE_SIMULATOR.md](PURCHASE_SIMULATOR.md). The earlier ticket-specific
design remains in [MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md) as architecture
research.
