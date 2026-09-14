# Belay internal payment protocol v0.1

**Historical card-based design, superseded September 13, 2026.** The selected
architecture now uses USDC and blockchain settlement without Stripe. Read
[the current protocol](INTERNAL_PAYMENT_PROTOCOL.md) and
[USDC architecture](USDC_SETTLEMENT_ARCHITECTURE.md) for implementation choices.
The decisions below are preserved as comparison material, not current guidance.

Status: proposed implementation contract, researched September 13, 2026.
The endpoints and records below are Belay designs, not deployed services or
AP2 schemas. The existing Purchase Simulator still uses fictional providers,
credentials, signatures and money. No merchant, issuing program, banking
access or funded guarantee is established by this document.

## 1. Decision in plain language

Belay should be the system that controls **what an agent may buy, executes
that purchase carefully, and establishes what happened afterward**.
Existing payment providers move the money. A merchant partnership can add
conditional release; it is not something a buyer's agent can impose.

Start with cards through an approved provider and one supported ticket seller.
Keep blockchain outside the initial payment path. Keep two explicit adapter
capabilities: ordinary merchant checkout and optional, contractually agreed
conditional checkout. Do not advertise the second when only the first exists.
This extends [the autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md)
and preserves [the recovery decision](RECOVERY_AND_GUARANTEE_DECISION.md).

### API, bank, wallet and credentials provider

| Term | Meaning in this design |
|---|---|
| API | A defined way for programs to request work or retrieve records. An endpoint is an address for a particular operation. An API is neither an AI model nor a bank account. |
| API credential | Identifies/authenticates the calling service and its permissions. It is not the customer's money and does not authorize arbitrary purchases. |
| Payment credential | A token or card credential that a supported checkout can present for payment. Its provider and payment profile determine its restrictions. |
| Credential provider | The service that keeps payment instruments and releases an authorized usable credential. A wallet provider, issuer or tokenization service can fill this role. |
| Consumer wallet | An interface to saved payment methods and approvals. It may store references to cards rather than holding a cash balance itself. |
| Belay wallet view | Proposed display of delegated limits, funding-method references and activity. The displayed budget is an internal permission limit, not a deposit account. |
| Crypto wallet | Manages keys or signing access used to control blockchain assets; the assets are recorded on the chain. Custodial services may manage those keys for users. |
| Payment rail | The underlying system that moves money, such as card networks, bank transfers or a blockchain. Each can be reached through APIs. |

A typical card path is:

```mermaid
flowchart LR
    U[User grants purchase scope] --> B[Belay checks and records purchase]
    B --> C[Credentials provider]
    C -->|Scoped credential through protected adapter| B
    B -->|Order and payment credential| M[Merchant checkout]
    M --> P[Merchant processor and acquiring bank]
    P --> N[Card network]
    N --> I[Issuing bank or card program]
    I -->|Authorization decision via network| P
    P -->|Payment status| M
    M -->|Order and fulfillment evidence| B
```

This is the authorization/request path, not an instantaneous settlement diagram.
Belay's buyer-side API key is different from the merchant's processor key.
Access to one account does not give control over the other. API keys stay in
the backend secret store; the model receives safe references and summaries.
[Stripe API authentication](https://docs.stripe.com/keys)

An approved Issuing program is a candidate for autonomous spending, subject
to access, funding and the supported customer use case. Its programmatic
checkout path has additional eligibility/preview requirements. Link's current
consumer spend-request flow requires approval for each request, so it does
not deliver our standing-delegation experience by itself.
[Issuing for agents](https://docs.stripe.com/issuing/agents),
[programmatic checkout](https://docs.stripe.com/issuing/agents/programmatic-checkout),
[Link spend requests](https://docs.stripe.com/agentic-commerce/link-cli/use-link-wallet-pay-online)

Bank-data access also does not mean payment authority. A bank debit needs a
supported payment integration and the applicable authorization/mandate.
[Financial Connections and ACH](https://docs.stripe.com/financial-connections/ach-direct-debit-payments)

## 2. Who controls the money?

| Mode | What happens to the customer's money? | Who can release/capture it? | Use in Belay |
|---|---|---|---|
| `merchant_checkout` | Merchant charges using its ordinary checkout flow. | Merchant and its payment provider. | Initial integration. Belay checks, submits, observes and requests remedies. |
| `partner_authorize_then_capture` | Issuer authorizes a temporary hold; capture follows agreed evidence. | Merchant, or an explicitly authorized integration acting for it. | Optional participating-merchant capability for promptly verifiable fulfillment. |
| `platform_conditional_transfer` | Customer is charged first; an agreed amount is transferred to an onboarded seller later. | Approved platform/payment arrangement. | Later product with onboarding, funds-flow and loss-responsibility work. |
| `provider_escrow` | An eligible escrow provider holds funds under agreed terms. | Provider's release/dispute process. | Separate future integration if the transaction and parties qualify. |

For cards, distinguish these stages:

1. **Authorization:** the issuer approves and normally holds available funds/credit.
2. **Capture:** the merchant submits the authorized amount for payment completion.
3. **Settlement:** the payment moves through the financial system.
4. **Transfer:** in a platform flow, money moves to a connected seller balance.
5. **Payout:** that balance is paid to the seller's external bank account.

These stages are not interchangeable with delivery. An internal Belay budget
reservation does none of them.

Online card authorizations commonly last roughly 5–7 days, with variations.
Use the actual charge's `capture_before`, not a fixed timer. Ordinary partial
capture releases the unused authorization. Eligible multicapture has separate
access and network-use restrictions; it is not a generic installment feature.
[Authorization and capture](https://docs.stripe.com/payments/place-a-hold-on-a-payment-method),
[multicapture constraints](https://docs.stripe.com/payments/multicapture)

In a Connect separate-charge flow the platform creates the customer charge
and separately transfers funds to sellers. Availability of charge funds does
not establish delivery; Belay would need its own agreed release controller.
[Separate charges and transfers](https://docs.stripe.com/connect/separate-charges-and-transfers)

Delaying a payout is not escrow. Stripe explicitly says it does not provide
escrow accounts. In relevant platform charge models, refunds and disputes
debit the platform; refunding a charge does not automatically reverse seller
transfers. The platform must account for recovery and liquidity separately.
[Manual payouts](https://docs.stripe.com/connect/manual-payouts),
[platform refunds and disputes](https://docs.stripe.com/connect/marketplace/tasks/refunds-disputes)

## 3. A $280 ticket purchase

The user delegates: “Buy two adjacent tickets for this event, this date,
through an allowed seller, for at most $300 including fees, before this deadline.”
That grant permits eligible purchases without routine repeated approval.
Required bank verification or a new purchase outside the grant still pauses.

### Ordinary merchant checkout

1. Merchant quotes two exact seats for $280 and identifies quote expiry.
2. Belay validates the quote and atomically reserves $280 of permission budget.
3. The protected adapter obtains an eligible payment credential and submits
   the exact saved order using a stable provider request identity.
4. The merchant's processor obtains authorization and captures under the
   merchant's normal policy. Belay cannot override that policy.
5. Belay reconciles payment and order records, then checks ticket fulfillment.
6. If tickets fail to arrive, Belay follows the merchant/provider's supported
   cancellation, refund or dispute process. A refund is a separate action.

“Paid” and “tickets delivered” are separate messages in the customer view.

### Participating seller: verify ticket transfer before capture

1. Seller agrees in advance to authorize $280 and delay capture.
2. Belay records the real authorization expiry and an earlier safety deadline.
3. Seller transfers the specified tickets under the agreed arrangement.
4. An authenticated ticket provider confirms the agreed recipient/ownership
   state for those exact tickets. A screenshot or seller-authored PDF alone
   does not satisfy this policy.
5. The authorized merchant integration captures $280 while authorization is
   still valid; Belay reconciles the capture response.
6. Missing evidence before the safety deadline triggers the agreed cancellation
   path. If ticket transfer or capture is uncertain, reconcile it rather than
   claiming the trade has been reversed.

There is still a delivery/capture gap: capture could fail after ticket transfer.
The merchant must accept that risk or use a supported reservation/revocable
transfer mechanism. No local database transaction makes both systems atomic.
Do not silently enable capture-on-expiry if the promise was delivery first.

Ticket ownership now does not prove admission at a concert months later.
Direct purchase, transfer-status and redemption APIs require the relevant
ticket provider access; do not assume an event-search API grants it.
[Ticketmaster Partner API](https://developer.ticketmaster.com/products-and-docs/apis/partner/)

### Participating platform: illustrative 80/20 release

Ignoring fees, the customer is charged $280. Under agreed platform terms,
$224 is transferred to the seller and $56 is retained until a defined event.
This is delayed seller transfer, not a partly uncharged customer payment.
If the full purchase is fraudulent, $56 covers at most $56 of the $280 loss;
the other $224 still needs recovery or a designated loss bearer. The split
is an illustration, not a validated commercial offer.

### Three receipts, three meanings

| Record | What it establishes | What it does not establish |
|---|---|---|
| Order confirmation | Merchant accepted an identified order. | Successful payment or usable tickets. |
| Payment confirmation | A specific authorization/capture state at the payment provider. | Correct seats, delivery or future entry. |
| Fulfillment evidence | The specified delivery/ownership event reported by an accepted source. | Every future outcome, such as an uncanceled event. |

Waiting for a receipt that is generated by capture before allowing that same
capture creates a circular dependency. Define the required *fulfillment*
evidence instead, and verify that the seller can supply it before capture.

## 4. Internal infrastructure and records

Start with one backend, one worker, a transactional database and explicit
provider adapters. Production can use PostgreSQL, a durable outbox/inbox and
a managed secret/signing service. This design does not require many separately
deployed services or a custom blockchain.

| Module / record | Responsibility |
|---|---|
| Identity and `grants` | User/account isolation, permitted mission/actions, caps, expiry, revocation and version. |
| Planner and `quotes` | Research and proposals; preserve exact seller, items, price, fees, currency and expiry. No spending credentials for the planner. |
| Authority and `budget_entries` | Validate current scope and serialize reservations against shared mission/account limits. |
| `purchases` and `actions` | Immutable purchase intent; child actions for submit, authorize, capture, void, refund and transfer. |
| Protected signer | Use the agent's delegated key through a restricted signing API; never impersonate the user's signature. |
| Executor and `outbox` | Persist a command before sending it; apply provider-specific retry and reconciliation rules. |
| Adapter registry | Authenticated provider identity, capabilities, account permissions, token limits and agreed release terms. |
| `inbox` and `evidence` | Verify event sources, retain raw evidence safely, deduplicate and bind it to exact operations. |
| Recovery and release controller | Reconcile uncertainty; request authorized remedies; evaluate deterministic release conditions. |
| Activity and support | Explain financial/order/delivery states separately and expose unresolved cases. |

AP2 can carry supported delegation/payment proofs between participants. In
its human-not-present flow, initial user authority and later transaction-bound
agent signatures have different roles. Use the exact version/profile accepted
by counterparties, with its canonical signing rules. A2A carries agent messages;
neither message transport nor a signed mandate grants bank or inventory access.
[AP2 flows](https://ap2-protocol.org/ap2/flows/)

An adapter must declare: funds controller; account and merchant scope; supported
payment methods; manual-capture eligibility; actual authorization deadline;
idempotency scope and retention; exact-object lookup and consistency behavior;
webhook authentication; fulfillment evidence source; refund/void/transfer
authority; and the versioned merchant agreement for conditional release.
Unsupported capabilities fail closed, rather than downgrading promised terms.

Provider token restrictions supplement Belay's exact-order checks. A token's
amount limit does not prove the purchased seats, and a shared payment token
must not be presumed to permit exactly one charge. Some provider controls
apply to authorization without governing every later capture. Record actual
financial outcomes even when they exceed the intended permission budget.
[Shared payment tokens](https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens?agent-seller=agent),
[Issuing transaction behavior](https://docs.stripe.com/issuing/purchases/transactions)

## 5. Proposed internal API

All names and IDs below are fictional Belay examples. They do not invoke Stripe
or a bank. Money uses integer minor units, explicit currency and immutable
quote snapshots. Callers are authenticated and authorized for the relevant
account; knowing an ID is not sufficient access.

```http
POST /internal/v1/purchases
Authorization: Bearer DEMO_NOT_A_REAL_SERVICE_TOKEN
Idempotency-Key: demo_mission_41_slot_1
Content-Type: application/json
```

```json
{
  "mission_id": "demo_mission_41",
  "purchase_slot": "tickets_for_event_1",
  "grant_version": 3,
  "quote_ref": "demo_quote_91",
  "mode": "merchant_checkout",
  "funding_method_ref": "demo_funding_7"
}
```

The server loads the account-owned quote, validates its exact contents and
reserves its $280 total. A client cannot change a quote by changing an amount
in this request. Same identity with different inputs is a conflict.

```json
{
  "purchase_id": "demo_purchase_62",
  "revision": 1,
  "submission": "prepared",
  "reserved_minor": 28000,
  "currency": "USD",
  "payment": "not_submitted",
  "fulfillment": "pending"
}
```

Return HTTP 202 for accepted asynchronous work. It does not mean the customer
has paid. The server owns mission-slot identity; a model cannot bypass an
unresolved purchase by inventing another request key.

| Proposed endpoint | Allowed caller and behavior |
|---|---|
| `GET /internal/v1/purchases/{id}` | Account-authorized reader; current observations and evidence references. |
| `POST /internal/v1/purchases/{id}/reconcile` | Authorized recovery controller; enqueue provider reads, not another purchase. |
| `POST /internal/v1/purchases/{id}/actions` | Guarded executor only; action kind, exact amount, parent identity and expected revision. Rechecks authority/capabilities for each new mutation. |
| `POST /internal/v1/provider-events/{adapter}` | Verified provider events; durable inbox before acknowledging accepted events. |

Every financial child action gets its own stable ID and provider idempotency
key. A retry retains them; a refund does not reuse the original purchase's
key. Scope keys to the provider account and operation, save a payload hash,
and retain local identities beyond the provider's key lifetime. Stripe can
prune idempotency keys after at least 24 hours; retry policy must account for
that window. A new key after a timeout is not a recovery strategy.
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)

The existing simulator's `/api/runs` endpoints are a different, local demo
interface. None of these `/internal/v1` routes are implemented yet.

### Where the real processor API fits

For an eligible Stripe merchant/platform integration, these are actual API
operations. They run with the authorized account's backend credentials, not
the buyer's Belay login or a key invented by the model. The ticket seller's
own order/fulfillment API remains a separate integration.

| Intended operation | Actual Stripe interface | Required controller |
|---|---|---|
| Prepare a payment with manual capture | [`POST /v1/payment_intents`](https://docs.stripe.com/api/payment_intents/create), using `capture_method=manual`; attach an eligible payment method and confirm to request authorization. Creating the object alone is not a hold. | Authorized merchant/payment account. |
| Capture an eligible authorization | [`POST /v1/payment_intents/{id}/capture`](https://docs.stripe.com/api/payment_intents/capture) | That payment account, subject to its capturable state/amount. |
| Read a payment after a lost reply | [`GET /v1/payment_intents/{id}`](https://docs.stripe.com/api/payment_intents/retrieve) | Account permitted to read that exact object. |
| Cancel an eligible uncaptured payment | [`POST /v1/payment_intents/{id}/cancel`](https://docs.stripe.com/api/payment_intents/cancel) | That payment account; current status determines eligibility. |
| Request a refund | [`POST /v1/refunds`](https://docs.stripe.com/api/refunds/create), bound to the original payment. | Account with refund authority. |
| Transfer funds to an onboarded seller | [`POST /v1/transfers`](https://docs.stripe.com/api/transfers/create) | Approved Connect platform with available funds and appropriate arrangement. |

In ordinary buyer-only checkout, Belay does not call these merchant mutations.
It uses the seller's checkout and the observations/remedies its buyer-facing
integration permits. A platform-owned PaymentIntent would change who charges
the customer and carries responsibilities; it is not a shortcut to controlling
an unrelated seller's payment.

## 6. Atomic operations and interlocks

An **atomic database operation** either commits all its local changes or none.
An **interlock** refuses an action until its conditions are satisfied.
Neither term means that the bank, merchant and ticket provider share one
all-or-nothing transaction with Belay.

For a new purchase, one database transaction must:

1. Lock the relevant account/mission budget and purchase slot.
2. Validate current grant, exact quote, deadline and adapter capability.
3. Check `committed_spend + active_reservations + proposed_amount <= cap`.
4. Reserve the amount, create immutable intent/action and add an outbox command.
5. Commit all those local changes together.

Unknown submissions stay in active reservations until authoritative evidence
allows a state change. Deduplicate captures by provider financial identity,
not merely webhook delivery ID. Each confirmed capture moves only its amount
from reserved to spent. If $100 of $280 is captured, preserve the remaining
$180 exposure until authoritative final-capture, cancellation or expiry
evidence resolves it. Do not free that remainder merely because a first
capture arrived. Default v0.1 mission budgets measure gross spend: even a
confirmed refund does not automatically replenish the mission's spending
authority. A changed budget requires an explicit grant update. Unexpected
external overcapture must appear as an exposure/limit breach, not be discarded
to preserve the displayed invariant.

Financial child actions require atomic admission too. Lock the parent and
relevant amount ledger, check expected revision and conflicting actions,
reserve the still-capturable/refundable/transferable amount, then insert the
immutable child action and outbox record in the same transaction. Uniqueness
of a logical release/refund instruction is enforced by the server. Two workers
cannot create different action IDs for the same release milestone and bypass
the protection by using different provider idempotency keys.

The worker claims commands and rechecks current authority immediately before
new external mutations. Its local dispatch transaction checks authority and
marks the exact action as submitting together. Revocation committed before
that transaction blocks dispatch; revocation after it cannot guarantee that
the external effect is stopped. Record this local dispatch point and explain
the remaining read/send race; it is not a remote commit point. The worker
does not hold a database lock during network calls.
Worker leases alone cannot stop a remote request already in flight. Combine
stable provider identities with reconciliation; never promise globally
exactly-once behavior when the provider cannot support it.

| Action | Interlock |
|---|---|
| Submit purchase | Valid scope/quote, reserved budget, supported credentials, no conflicting unresolved purchase slot. |
| Capture in partner mode | Merchant authorization to act, live capturable amount, agreed verified evidence, deadline safety margin and no blocking case under the terms. |
| Seller transfer in platform mode | Funds available, agreed release milestone met, exact seller account and unreleased amount verified, no conflicting pending transfer/refund. |
| Refund | Authority to request it, correct original payment, eligible amount minus prior/pending refunds and coordinated dispute recovery. |
| Complete customer task | Required payment, exact order and fulfillment evidence all satisfied; otherwise show their separate states. |

Do not implement a capture interlock for a merchant account Belay cannot
control. Canceling a local task or revoking a grant cannot recall a request
that the remote provider has already accepted.

## 7. Independent state and evidence

Track separate axes rather than one ambiguous `success` flag:

| Axis | Example observations |
|---|---|
| Submission | prepared, in_flight, requires_action, confirmed, failed, unknown |
| Payment | not_submitted, authorized, capture_pending, partially_captured, captured, void_pending, voided, failed, unknown |
| Order | reserved, accepted, cancel_pending, canceled, failed, unknown |
| Fulfillment | pending, transferred, verified, rejected, unknown |
| Seller funds | uncontrolled, withheld, transfer_pending, transferred, paid_out, unknown |
| Refund | none, pending, succeeded, failed, unknown |

`Unknown` means Belay lacks evidence; the provider may already know the result.
Record source, provider account, object IDs, observation time, amount/currency,
quote/item identity and verified signature or authenticated retrieval context.

Webhook delivery can repeat and arrive out of order. Verify signatures over
the required raw body, durably record the event, deduplicate by provider account
and event identity, and apply state/effect guards. Resolve conflicting events
through authoritative object retrieval; do not simply let the last arriving
event overwrite state. Access only the payment accounts we are entitled to
observe. [Stripe webhooks](https://docs.stripe.com/webhooks)

## 8. Scenarios the implementation must handle

| Scenario | Required behavior |
|---|---|
| $280 valid quote under a $300 grant | One reserved operation; supported checkout; payment/order/fulfillment tracked separately. |
| Price changes to $320 | Reject under current grant before a new payment submission; never quietly expand the cap. |
| Two agents compete for the same budget/slot | Database serialization admits only the permitted operation(s); do not depend on model memory. |
| Two workers submit the same action | Same persisted payload and provider identity; reconcile according to adapter guarantees. |
| Charge/order commits but response is lost | Keep reservation and unresolved slot; query exact operation; no fresh purchase key. |
| Provider lookup returns nothing | Respect consistency and search scope; an empty response alone does not prove absence. |
| Bank requires customer verification | Pause and surface the provider step; recheck authority/quote before any subsequent new mutation. |
| User revokes while request is in flight | Stop new submissions; reconcile the in-flight result and available cancellation/refund options. |
| Partner cannot prove delivery before hold deadline | Follow agreed cancellation/reconciliation path; do not silently charge just to avoid expiry. |
| Ticket transfer succeeds but capture fails | Preserve fulfillment state; invoke the agreed seller remedy/recovery path; never claim atomic rollback. |
| Captured payment but no valid tickets | Investigate and request supported remedy. Show pending refund honestly; no unfunded automatic compensation. |
| Fake PDF, wrong seats, foreign account or replayed event | Reject as release evidence; bind every observation to this purchase and its accepted source. |
| Duplicate or late webhook | Durable deduplication and state guards; resolve conflicts against the provider record. |
| Seller transfer times out | Retain pending release; reconcile its exact identity before another transfer. |
| Refund and dispute overlap | Coordinate amounts and existing recoveries to avoid duplicate credit or double reimbursement. |
| Merchant declines conditional terms | Offer only an arrangement allowed by the user's existing scope, or stop; never silently weaken promised protection. |

The lost-reply case is not purely hypothetical: Ticketmaster documents an
error that can occur after an order commit succeeds. Its integration guidance
requires checking the existing order rather than assuming failure.
[Partner API error handling](https://developer.ticketmaster.com/products-and-docs/apis/partner/)

## 9. Will merchants agree, and would blockchain help?

Merchant willingness is unvalidated. The business case to test is additional
customers and lower dispute costs in exchange for predictable release terms.
The objections are working-capital cost, failed capture after delivery, false
buyer complaints, fees and uncertain release dates. A buyer-only “release
whenever I feel satisfied” button is not a workable mutual-trust mechanism.

A pilot agreement must name the funds controller, acceptable fulfillment
evidence, deadlines, cancellation rules, dispute decision maker, fees and loss
bearer. Start with an agreed digital delivery milestone measurable in minutes.
Do not assume a major ticket marketplace will change its settlement terms.
Provider escrow has its own eligibility, inspection and dispute process.
[Example escrow inspection process](https://www.escrow.com/support/faqs/what-is-an-inspection-period,-when-does-it-start,-and-how-long-does-it-last)

A smart contract can condition release of funds it actually controls. It
cannot undo a card payment or discover real-world delivery by itself. It needs
external evidence/an oracle for ordinary tickets and goods. An atomic exchange
of compatible on-chain assets is possible under the relevant contract's rules;
that does not make event entry or physical delivery atomic. A refund after
release is another authorized transfer, not a rewind of history.
[Ethereum oracles](https://ethereum.org/developers/docs/oracles/)

For Belay, a blockchain would add integration and custody choices without
solving the initial evidence problem. Revisit it only when a merchant accepts
the rail and it supplies a concrete benefit to an agreed release arrangement.
No payment rail or protocol alone prevents all fraud. Signatures prove signed
data and authority under a trust model; they do not prove that a seller's claim
about a product is true.

## 10. Implementation sequence and acceptance gates

1. Extend the local simulator with separate authorization/capture/fulfillment
   states and explicit partner-mode consent. Keep every external service mocked.
2. Implement the internal command, budget, outbox/inbox and reconciliation
   contracts with deterministic failure/concurrency tests.
3. Integrate one approved funding provider and merchant in their supported test
   environments. Verify permissions, exact idempotency/lookup behavior and each
   scenario above before enabling real purchases.
4. Pilot conditional release only after the merchant, provider and operating
   model support it. Publish the exact protection and remaining exposure.

The current change specifies this work; it does not claim those stages are
complete. Preserve the research runtime, Recovery Lab and Purchase Simulator
boundaries in [INTEGRATION.md](INTEGRATION.md). A future guarantee remains a
separately authorized and funded remedy, not a property of this protocol.
