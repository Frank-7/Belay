# Belay internal payment protocol v0.2: USDC

Status: current proposed interface, September 13, 2026; not implemented.
The user selected blockchain/USDC settlement. The former card design is
preserved in [PAYMENT_PROTOCOL_CARD_REFERENCE.md](PAYMENT_PROTOCOL_CARD_REFERENCE.md).

The authoritative design is [USDC_SETTLEMENT_ARCHITECTURE.md](USDC_SETTLEMENT_ARCHITECTURE.md):
Base native USDC, owner-prefunded mission grants, a constrained order executor,
contract escrow, verified delivery/dispute allocation and seller-controlled
conversion to bank money. Stripe is not in the selected integration path.

## API roles

- Belay API: account-authenticated proposals, workflow state and evidence.
- Wallet/signing API: owner approvals and restricted agent/service signatures.
- Blockchain RPC: reads and transaction submission; an RPC key does not grant
  control over a wallet or settle a transaction by itself.
- Contract ABI: exact grant/order/release/refund functions and on-chain checks.
- Conversion API: approved provider quotes, hosted sessions and payout status.
- Merchant API: offers, accepted orders and fulfillment evidence.

## Proposed routes

All `/internal/v1` endpoints below are new designs. The existing `/api/runs`
interface belongs to the fictional Purchase Simulator and is unchanged.

| Route | Caller and behavior |
|---|---|
| `POST /internal/v1/funding-sessions` | Authenticated owner; request an eligible provider session bound to its verified wallet, asset/network and funding cap. It does not automatically debit a bank account. |
| `POST /internal/v1/grants` | Owner intent; prepare the exact fundGrant call/terms for owner wallet approval. Confirm funding from chain evidence before making the grant spendable. |
| `POST /internal/v1/purchases` | Planner proposal; validate grant/quote, allocate stable order/slot identity, reserve local budget and persist outbox atomically. |
| `GET /internal/v1/purchases/{id}` | Account-scoped view of order, escrow, evidence, withdrawals and optional conversion status. |
| `POST /internal/v1/purchases/{id}/reconcile` | Authorized controller; reconcile chain/provider records without creating another economic order. |
| `POST /internal/v1/purchases/{id}/delivery-evidence` | Accepted verifier; validate exact evidence and signature, enqueue eligible attestation. |
| `POST /internal/v1/purchases/{id}/disputes` | Owner or authorized representative; prepare/relay the signed dispute call. |
| `POST /internal/v1/purchases/{id}/actions` | Protected executor; guarded contract calls only. Model cannot invoke release/resolution arbitrarily. |
| `POST /internal/v1/cashout-sessions` | Seller; retrieve an eligible conversion quote/session for its own wallet/provider account. No arbitrary destination redirect. |
| `POST /internal/v1/provider-events/{adapter}` | Authenticate provider signature, durably deduplicate and enqueue reconciliation. |

## Example: request a 42 USDC order

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
  "quote_ref": "demo_quote_42_usdc",
  "settlement_mode": "usdc_contract_escrow"
}
```

```json
{
  "purchase_id": "demo_purchase_62",
  "revision": 1,
  "submission": "prepared",
  "amount_base_units": "42000000",
  "asset": "USDC",
  "network": "base",
  "escrow": "not_funded",
  "delivery": "pending",
  "seller_withdrawal": "not_available",
  "fiat_payout": "not_requested"
}
```

HTTP 202 means the workflow accepted the command, not that escrow is funded.
The server owns stable mission-slot identity and rejects the same identity
with different inputs. Atomic local reservations prevent competing proposals;
contract checks independently enforce the funded budget and order uniqueness.

## Protected action mapping

| Backend operation | Proposed contract action | Independent evidence |
|---|---|---|
| Fund bounded mission | `fundGrant` | Successful canonical transaction and exact grant state/token credit. |
| Commit accepted quote | `openOrder` | Exact contract/order allocation and confidence level. |
| Record delivery | `attestDelivery` | Pinned verifier signature plus private source evidence. |
| Release after challenge interval | `finalize` | Contract policy/time/state; resulting allocation. |
| Refund non-delivery | `refundUndelivered` | Deadline and absence of timely accepted attestation in contract state. |
| Allocate disputed funds | `resolve` or `refundUnresolved` | Pinned resolver authority or fixed timeout rule. |
| Receive allocated USDC | `withdraw` | Successful token transfer to recorded beneficiary. |
| Cash out | Provider-specific hosted/API flow | Conversion/deposit and bank-payout records; not a contract action. |

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
