# Belay payment-mission MVP

This local application is the runnable Belay investor demonstration. A customer
describes a payment in ordinary language. Belay turns it into a reviewable
plan, asks for any missing payee, amount or required reference, records one
exact authorization, and executes a durable simulated USDC-to-USD payment.

The customer experience and **Behind this action** view use the same persisted
event. An investor can watch the simple product flow and inspect the policy
decision, money route, stable operation identity, provider result, ledger and
receipt without switching to a separate demonstration.
An uncertain payout can be investigated in the same view through the shared
Recovery Desk validator, then explicitly reconciled without another send.

## Run it

From a clone with Python 3.10 or newer:

```bash
python -m purchase_simulator.server --port 8777
```

Open `http://127.0.0.1:8777`. The server listens on loopback only. No API key,
package installation or payment account is required.
The preserved ticket, delivery and reserve scenarios run at
`http://127.0.0.1:8777/purchase/` on the same server.

An installed wheel also provides the same launcher:

```bash
belay-mission --port 8777
```

On Windows, double-click `Start-Belay-Simulator.cmd`. Leave its terminal open
while using the app. The launcher tries the bundled Codex Python runtime, then
`py -3`, then `python`. It stores the current walkthrough under
`.belay-purchase-simulator/mission-v1/` so earlier ticket-demo state cannot
appear in the investor flow.

The server's default data directory remains `.belay-purchase-simulator/`.
Pass `--data-dir PATH` for an isolated rehearsal. Restarting against the same
directory preserves missions, events, value movements and fictional provider
records in SQLite.

## Three-minute investor walkthrough

1. Enter a request such as `Pay invoice INV-1042 for $1,250 to Acme Design by
   September 30`, enable **Simulate a lost payout reply**, and select
   **Prepare payment**.
2. Show that the payee, exact amount, limit, reference and due date are visible
   before authorization. Edit any field to demonstrate that the customer's
   reviewed plan is the source of authority.
3. Select **Authorize one payment**. The authorization fixes the beneficiary,
   amount, reference, assets, stable operation ID and 30-minute expiry.
4. Let Belay execute. The customer sees plain progress while the backend pane
   shows deterministic checks, a single-use hold, a bound payment instruction,
   one provider dispatch and a simulated USD payout.
5. When the payout becomes uncertain, investigate its evidence. The finding
   does not move money. Explicitly reconcile the confirmed original payment,
   then open the final receipt. It links what the customer requested, what they
   authorized, what was paid and what the domain-specific confirmation proves.
6. Start a tax or insurance request with a missing amount. Belay leaves the
   amount blank and asks for it. It does not invent a money-moving fact.

The example prompts are shortcuts into the same composer. The lost-reply
toggle changes only the labeled fictional provider outcome, using the same
review, authority and payment identity.

## Requests the MVP can shape

The input accepts open-ended payment text. A deterministic local extractor
currently recognizes these domain templates:

| Domain | Required review | Receipt boundary |
|---|---|---|
| Invoice | Payee, amount and invoice reference | Confirms payment; delivery remains external |
| Bill | Biller, amount and account or bill reference | Confirms payment; service status and remaining balance remain external |
| Insurance premium | Insurer, amount and policy number | Confirms premium payment; coverage and claims remain external |
| Tax payment | Agency, amount and tax period or notice | Confirms payment instruction; it does not calculate tax or file a return |
| Subscription | Provider and amount | Authorizes one payment; no recurring mandate is created |
| Transfer | Beneficiary and amount | Confirms the reviewed beneficiary payout |
| Tickets or travel | Seller and amount | Confirms payment and order submission; fulfillment remains external |
| Other purchase | Payee and amount | Confirms payment; product or service delivery remains external |

Classification only changes the questions and the receipt wording. The
payment-control path is shared. Unknown categories fall back to a general
purchase plan instead of failing. The extractor is intentionally conservative:
it may recognize familiar example fields, but every field stays editable and
the customer must authorize the completed plan.

## What runs behind the screen

```text
plain-language request
        |
        v
reviewable plan ---- missing facts? ----> ask customer; no money moves
        |
        v
one exact authorization
        |
        v
15 deterministic checks
        |
        v
single-use USDC hold -> bound instruction -> settlement adapter -> payee USD
        |                                                        |
        +---------------- linked event, ledger and receipt ------+
```

The implemented mission lifecycle is:

```text
needs details / ready -> authorized -> checked -> held -> signed
                      -> dispatched -> paid -> complete
                                    -> payout unknown -> investigate
                                                      -> reconcile -> paid
```

- **Intent compiler:** converts text into a draft. It cannot authorize or move
  money.
- **Plan editor:** saves customer-reviewed fields under an expected revision.
  A stale browser action cannot overwrite a newer plan.
- **Authority service:** creates one bounded local grant for the exact plan.
- **Policy service:** checks approval, beneficiary, amount, maximum, funding,
  reference, asset route, one-time scope, expiry and operation identity in
  ordinary code outside the agent.
- **Treasury:** records the exact simulated USDC hold and balance change in one
  local SQLite transaction.
- **Protected signer:** creates a digest over the grant, beneficiary, amount,
  reference and stable operation ID. The displayed signature is a mock marker.
- **Payment executor:** dispatches only the saved instruction and reuses the
  stable operation identity.
- **Settlement adapter:** records one simulated conversion and USD payout.
- **Receipt service:** links the request, authorization, payment and scoped
  confirmation. It does not turn payment evidence into delivery, filing or
  coverage evidence.

The demo wallet starts with 25,000 fictional USDC and accepts an exact payment
up to $25,000. For readability it assumes 1 USDC = $1.00 and no fees. These are
demonstration fixtures, not price, liquidity or settlement promises.

## What is real and what is simulated

The browser makes actual HTTP requests to a loopback Python server. The server
uses real SQLite transactions, revision guards, unique idempotency keys,
persisted operation records, a conserved local balance and generated digests.

Everything outside that process is fictional. No language model, customer
wallet, blockchain, exchange, bank, payee, biller, insurer, government agency,
merchant, tax system, coverage or money is connected. `.invalid` and
`belay://` routes shown in the audit are descriptive and are never contacted.
The local signature is not production cryptography. The beneficiary check is
a simulated status, not KYC, AML, sanctions screening or bank-account
verification.

This MVP demonstrates the product contract and durable control path. A live
deployment needs authenticated users, reviewed custody and money-transmission
roles, production key custody, a regulated USDC-to-USD settlement provider,
verified payee adapters, provider-specific idempotency and reconciliation,
compliance controls, monitoring and operational support. A government or
insurer adapter must return authoritative acceptance evidence before Belay can
claim that an obligation was satisfied.

## Legacy v0.3 recovery bridge

The same server retains the earlier `belay.purchase.v0.3` ticket workflow for
compatibility. Its payout-reply-lost path now demonstrates a stricter recovery
boundary. Before provider I/O, Belay commits a `dispatch_attempts_v3` record for
the exact run, order, operation and canonical payment intent. Once dispatch may
have started, the customer hold stays reserved; expiry or cancellation cannot
release it based only on a missing reply.

The typed investigator in `purchase_simulator/recovery.py` and
`recovery_app/purchase.py` reads only the original provider operation. It binds
the mission and order identities, grant digest, beneficiary, six-decimal USDC
base units, USD cents and canonical intent. It returns `paid`, `unknown` or
`conflict`, and only exact paid evidence sets `can_reconcile`. A missing record,
provider outage, partial status or disagreement cannot release funds or permit
another submission.

When the legacy executor reconciles, it reads the provider again and rejects a
changed evidence digest. The original payout is accounted once; no browser
verdict is accepted and no investigation callback can sign, submit, convert,
complete or pay a claim. This bridge currently covers one fictional lost-payout
path. The universal `belay.mission.v0.1` interface uses a separate domain-neutral
intent adapter over the same `recovery_app/payment.py` validator. It preserves
the distinction between USDC base units and USD cents without inventing an order
or projecting a general payment into the research refund schema.

Mission investigation is read-only and deterministic. The executor rereads the
provider and compares its evidence digest at reconciliation; a browser-supplied
verdict cannot authorize it. An unknown mission has no automatic advance or
replacement payment. Once a payment may have happened, grant expiry does not
prove that its funds can be returned.

## Local API

| Route | Body | Purpose |
|---|---|---|
| `GET /api/mission/config` | — | Read examples, limits, schema and the simulation notice |
| `POST /api/missions/analyze` | `request`, optional `demo_outcome` (`success` or `payout_reply_lost`) | Create and persist a draft payment mission |
| `GET /api/missions/{id}` | — | Read the current mission, events, ledger and provider result |
| `POST /api/missions/{id}/details` | `expected_revision`, `fields` | Save editable plan fields before authorization |
| `POST /api/missions/{id}/authorize` | `expected_revision` | Approve one exact, complete payment plan |
| `POST /api/missions/{id}/advance` | `expected_revision` | Execute one permitted transition |
| `POST /api/missions/{id}/investigate` | `expected_revision` | Read original-payment evidence without changing the mission or sending money |
| `POST /api/missions/{id}/reconcile` | `expected_revision`, `evidence_digest` | Revalidate fresh evidence and account the confirmed original payout once |

The editable fields are `payee`, `amount_usd_cents`,
`maximum_usd_cents`, `reference`, `due_date`, `description` and `category`. Amounts use
whole USD cents. A stale revision returns HTTP 409. The route never accepts a
wallet key, bank credential or raw payment token.

The earlier `GET /api/config` and `/api/runs` ticket-simulator routes remain
available through the `/purchase/` walkthrough. They use the separate
`belay.purchase.v0.3` schema and do not drive the current investor interface.
`POST /api/runs/{id}/investigate` accepts only `expected_revision` and returns
the read-only finding for that legacy run's original payout.

## Verify

```bash
python -m unittest discover -s tests -p "test_mission_control.py" -v
python -m unittest discover -s tests -p "test_mission_inputs.py" -v
python -m unittest discover -s tests -p "test_mission_recovery.py" -v
python -m unittest discover -s tests -p "test_purchase_simulator.py" -v
python -m unittest discover -s tests -p "test_purchase_recovery.py" -v
node --check purchase_simulator/web/app.js
node --test tests/test_purchase_simulator_ui.mjs tests/test_purchase_walkthrough_ui.mjs
python experiments/check_docs.py
```

The suites use temporary databases and no remote services. The mission tests
cover parsing, missing details, authorization bounds, the complete money path,
stable revisions, persistence and the loopback API. The legacy suite protects
the ticket workflow that remains available through its API and UI. The recovery suite
covers dispatch uncertainty, hold safety, exact evidence binding, unknown and
conflicting observations, current revisions and no replacement submission.

## Production adapter seams

The MVP keeps the future integrations behind narrow roles:

| Seam | Input Belay fixes | Evidence Belay must receive |
|---|---|---|
| Planner or agent | User request and non-secret context | Proposed structured plan; never authority |
| Wallet or custodian | Grant, asset, amount and stable operation ID | Hold or transfer status tied to that identity |
| Conversion and payout provider | Source units, destination cents and verified beneficiary | Quote, acceptance, final payout or reconciled unknown outcome |
| Payee-domain adapter | Reference and provider payment identity | Authenticated acceptance, filing, posting or fulfillment status |
| Receipt store | Digests and scoped evidence links | Durable receipt with source, time and meaning |

Adapters may fail or return an unknown outcome. Production code must reconcile
the original operation before retrying and must preserve the difference
between payment, payee acceptance and delivery. No single adapter should let an
agent expand its own authority.
