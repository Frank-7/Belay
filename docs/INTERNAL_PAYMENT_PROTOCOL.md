# Belay internal payment protocol v0.3: USDC to USD

> **Current scope — September 14, 2026:** Belay's AI Apps product centers on
> Recovery Desk. The Purchase Simulator is its fictional commerce use case and
> now reuses a typed, read-only recovery investigator. This document preserves
> the future commerce design; Base contracts, approved USD payout providers and
> funded protection remain external dependencies. The implemented wallet path
> is human-signed Arc Testnet, separate from the simulated USD payout. See
> [INTEGRATION.md](INTEGRATION.md) for what runs today.


Status: current proposed interface, September 13, 2026; not implemented.
The user selected blockchain/USDC settlement. The former card design is
preserved in [PAYMENT_PROTOCOL_CARD_REFERENCE.md](PAYMENT_PROTOCOL_CARD_REFERENCE.md).

The authoritative design is [USDC_SETTLEMENT_ARCHITECTURE.md](USDC_SETTLEMENT_ARCHITECTURE.md):
Base native USDC, owner-prefunded mission grants, a constrained order executor,
temporary order holds, approved conversion and USD payment to the supplier,
plus separately funded protection for eligible post-payment failures. The
supplier does not need a crypto wallet or exchange account. Stripe is not in
the selected integration path. Read [MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md)
for agent roles, evidence, protection and presentation scope.

## API roles

- Belay API: account-authenticated proposals, workflow state and evidence.
- Wallet/signing API: owner approvals and restricted agent/service signatures.
- Blockchain RPC: reads and transaction submission; an RPC key does not grant
  control over a wallet or settle a transaction by itself.
- Contract ABI: exact grant/order/release/refund functions and on-chain checks.
- Conversion API: approved provider quotes, hosted sessions and payout status.
- Merchant API: offers, accepted orders and fulfillment evidence.
- Protection API: reserve admission, evidence decisions, capped claims and recoveries.

## Proposed routes

All `/internal/v1` endpoints below are new designs. The existing `/api/runs`
interface belongs to the fictional Purchase Simulator and is unchanged.

| Route | Caller and behavior |
|---|---|
| `POST /internal/v1/funding-sessions` | Authenticated owner; request an eligible provider session bound to its verified wallet, asset/network and funding cap. It does not automatically debit a bank account. |
| `POST /internal/v1/grants` | Owner intent; prepare the exact fundGrant call/terms for owner wallet approval. Confirm funding from chain evidence before making the grant spendable. |
| `POST /internal/v1/purchases` | Planner proposal; validate exact order/quantity and USD quote, allocate stable order/slot identity, reserve user budget and promised protection, then persist guarded dispatch. |
| `GET /internal/v1/purchases/{id}` | Account-scoped order, held/dispatched funds, USD payout, delivery, receipt and protection state. |
| `POST /internal/v1/purchases/{id}/reconcile` | Authorized controller; reconcile chain/provider records without creating another economic order. |
| `POST /internal/v1/purchases/{id}/delivery-evidence` | Authenticated source/verifier; retain bound evidence. No automatic payout solely because the model says delivery happened. |
| `POST /internal/v1/purchases/{id}/disputes` | Owner or authorized representative; open an evidence-backed case under active terms. |
| `POST /internal/v1/purchases/{id}/actions` | Protected executor; guarded contract/provider operations. Model cannot invoke arbitrary transfers or claim decisions. |
| `POST /internal/v1/payout-quotes` | Authorized router; exact supplier USD amount, verified bank beneficiary and maximum source USDC/fees. |
| `POST /internal/v1/cases/{id}/decisions` | Separate authorized claims service/reviewer; evidence, coverage, net loss, reason and cap. |
| `POST /internal/v1/cases/{id}/payments` | Treasury executor; consume committed reserve capacity and pay original buyer once. |
| `POST /internal/v1/cashout-sessions` | Buyer; eligible optional conversion of restored USDC to its own bank money. |
| `POST /internal/v1/provider-events/{adapter}` | Authenticate provider signature, durably deduplicate and enqueue reconciliation. |

## Example: two tickets, supplier receives $200

This is an illustrative Belay request, not an exchange or blockchain RPC call.
Token address and chain are loaded from verified deployment configuration.

```http
POST /internal/v1/purchases
Authorization: Bearer DEMO_NOT_A_REAL_SERVICE_TOKEN
Idempotency-Key: demo_mission_41_slot_1
Content-Type: application/json
```

```json
{
  "mission_id": "demo_mission_41",
  "grant_ref": "demo_chain_grant_8",
  "purchase_slot": "concert_tickets",
  "quote_ref": "demo_two_tickets_200_usd",
  "payout_quote_ref": "demo_usdc_to_usd_1",
  "settlement_mode": "USD_PREPAY",
  "protection_terms_ref": "demo_cover_300_combined"
}
```

```json
{
  "purchase_id": "demo_purchase_62",
  "revision": 1,
  "submission": "prepared",
  "source_amount_base_units": "200000000",
  "asset": "USDC",
  "network": "base",
  "merchant_amount_minor": 20000,
  "merchant_currency": "USD",
  "held_funds": "not_committed",
  "delivery": "pending",
  "fiat_payout": "not_requested",
  "protection": "admission_pending"
}
```

This demo quote assumes 1:1 conversion and zero fees; real provider quotes
determine source cost and net USD received. No real keys/account details appear.
HTTP 202 means the workflow accepted the command, not that the merchant is paid.
The server owns stable mission-slot identity and rejects the same identity
with different inputs. Atomic local reservations prevent competing proposals;
contract checks independently enforce the funded budget and order uniqueness.

## Protected action mapping

| Backend operation | Proposed action | Independent evidence |
|---|---|---|
| Fund bounded mission | `fundGrant` | Successful canonical transaction and exact grant state/token credit. |
| Commit exact purchase | `commitOrder` plus protection reservation | Contract/order allocation, source quote and reserve capacity. |
| Fund USD route | `dispatchToProvider` | Canonical token transfer to approved provider route. |
| Convert and pay USD | Provider-specific conversion/payout APIs | Exact provider operation, net amount, bank beneficiary and lifecycle. |
| Record delivery | Evidence service | Accepted source and exact item/recipient observations. |
| Return still-held funds | `refundHeld` | No conflicting/in-flight dispatch and actual remaining balance. |
| Pay eligible post-payment loss | `payClaim` from protection reserve | Separate approved case, backed capacity, original buyer and net loss. |
| Recover supplier/provider funds | `recordReturnedFunds` after actual receipt | Authenticated return and credited funds; adjust prior compensation once. |
| Buyer cash-out | Eligible provider flow | Conversion/deposit and bank-payout records. |

Persist each action before broadcast. Bind signatures to chain, contract,
grant, order, quote/policy, amount and nonce. Save replacement transaction
lineage and reconcile canonical contract state on ambiguous results. Do not
equate RPC acceptance, transaction inclusion, finality, delivery and bank payout.

## Repo integration

Keep one controlled executor. The research adjudicator may contribute validated
findings through a reviewed adapter; it cannot directly sign releases or resolve
live disputes. Model outputs and existing synthetic dossiers are not trusted
delivery attestations. Keep chain/account/network isolation separate from the
local simulator databases, as described in [INTEGRATION.md](INTEGRATION.md).
