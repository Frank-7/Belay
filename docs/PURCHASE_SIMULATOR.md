# Belay protected-purchase simulator

This local application is the runnable Belay v0.4 investor demonstration. One
canonical event drives a synchronized customer view and backend control room for
the same fictional concert-ticket purchase. The shopping agent proposes an
offer, deterministic code checks it against the customer's grant, USDC funds a
simulated conversion, the merchant receives simulated USD, and delivery or
protection evidence closes the order.

The browser talks to a real loopback Python server and the server persists state
in SQLite. Everything beyond that boundary is a fixture: there is no live model,
wallet, blockchain, exchange, bank, merchant, ticket system, insurer or money.

## Run

From a repository clone with Python 3.10 or newer:

```bash
python -m purchase_simulator.server --port 8777
```

Open `http://127.0.0.1:8777`. No installation, API key or payment account is
needed. The server listens on loopback only. Use one server process per data
directory.

On Windows, double-click `Start-Belay-Simulator.cmd` in the repository folder.
Leave its terminal window open while using the app. The launcher tries the
installed Codex Python runtime, then `py -3`, then `python`, and stores v0.4 demo
runs under `.belay-purchase-simulator/demo-v4/`.

The server's default directory is `.belay-purchase-simulator/`. Pass
`--data-dir PATH` for an isolated demonstration. Restarting with the same path
preserves runs, ledger entries, claims and fictional provider records. A saved
run from an older schema is rejected with an instruction to begin a new v0.3
schema simulation; the launcher uses `demo-v4/` so the redesigned walkthrough
does not mix with earlier demo data.

## The main investor story

The default fixture starts with a customer grant of 300 USDC and a separate
fictional protection reserve containing 1,000 USDC. Two adjacent tickets cost
$100 each. For readability the demo assumes `1 USDC = $1.00` and zero fees.
Those assumptions are not pricing or settlement promises.

1. The customer authorizes exactly two adjacent tickets, from the named seller,
   with a maximum spend of 300 USDC.
2. The shopping agent proposes an exact offer. The model-shaped component can
   search and propose, but it cannot approve its proposal or move funds.
3. A payout quote binds 200 USDC in, $200 USD out, the seller beneficiary and
   the same stable operation identity.
4. Deterministic policy checks quantity, seller, event, date, adjacency, budget,
   assets and beneficiary. Admission holds 200 USDC and commits up to 300 USDC
   of separate protection capacity in one local database transaction.
5. A protected executor creates an immutable settlement instruction. Its
   signature is a labeled mock marker; no cryptography is performed.
6. The fictional provider receives 200 USDC once, converts it, and records a
   $200 USD payout to the merchant. The merchant never handles crypto in this
   flow.
7. Payment, merchant order acceptance and ticket delivery remain separate
   states. A final receipt links the grant, order, payout, delivery evidence and
   any remedy.

Use **Next event** to inspect every transition or **Auto play** for the
presentation. Six chapters keep the business story visible while the persistent
value map follows customer USDC, the order hold, the settlement provider,
merchant USD and protection reserve. The customer side explains the result in
plain language. The backend side exposes the exact actor, trust boundary,
control, proof, safe replay rule, request, response, state change and ledger
movement. Selecting any technical-history event rewinds both views to the same
point in time. On a narrow screen, use the Customer and Belay backend tabs to
switch between the synchronized views. All displayed credentials and `.invalid`
URLs are intentionally fictional.

## Scenarios

| Scenario | What happens | Expected result |
|---|---|---|
| Delivered — protected purchase | Two $100 tickets pass policy, 200 USDC funds the route and the tickets match the order | Merchant receives $200 USD once, the customer retains 100 USDC, no claim is paid and the demo releases its coverage commitment after verification |
| Payout reply lost — recover safely | The provider pays the merchant but its response disappears | Belay records an unknown outcome, performs a read-only lookup under the original operation ID and confirms one $200 payout without sending another |
| Merchant paid — tickets missing | The $200 merchant payout is final, but no tickets arrive | An independent claim is opened and approved; the reserve pays 200 USDC to the customer, falls to 800 USDC and hands supplier recovery to a flow outside this demo |
| Agent proposes three — blocked | The proposal conflicts with the signed two-ticket grant | Deterministic policy stops the order before a hold, coverage commitment or provider request; all 300 USDC remains available |
| Injected past error — buyer restored | A clearly labeled historical fixture starts after three $100 tickets were already bought despite a two-ticket grant | The unauthorized extra ticket is quarantined for return or resale; independent controls pay the contractual 100 USDC remedy once, the customer keeps the intended two tickets and the reserve falls to 900 USDC |
| Cancel before dispatch | A valid order is admitted and then cancelled before provider dispatch | The 200 USDC hold returns to the customer, the coverage commitment is released and the merchant receives nothing |
| Evidence conflicts — review | One source says delivered while another says missing | Automation abstains, no claim is paid and the case stays open for a human-review handoff that is not implemented in this demo |

The historical error is injected initial state. The normal execution path never
bypasses the quantity guard to manufacture a failure. Supplier non-delivery and
agent error are distinct loss types, and each claim has an economic-loss ID so
one loss cannot be paid twice in the local ledger.

## Reading the money view

The simulator keeps different assets and obligations separate:

| Field | Meaning |
|---|---|
| Customer available | USDC the customer can still use in this fictional run |
| Order hold | Customer USDC admitted for this exact order but not yet dispatched |
| Provider in transit | USDC sent to the conversion fixture and not yet reflected as merchant USD |
| Merchant received | USD cents recorded as paid to the merchant |
| Protection reserve cash | Separate fictional USDC available to fund eligible remedies |
| Coverage committed | Maximum protection capacity reserved for the order |
| Claim pending / paid | Approved but unpaid exposure, or USDC already moved from the reserve to the customer |

USDC base units and USD cents are never added into one balance. Committing
coverage does not move reserve cash. Paying an approved claim does. Once the
merchant has received USD, the original customer funds cannot be pulled back by
the blockchain. The non-delivery example therefore uses separate reserve cash
and shows the original merchant payment unchanged.

The demo commits a maximum combined 300 USDC of protection for the order. It
uses 200 USDC for the supplier non-delivery example or a contractual 100 USDC
remedy for the unauthorized extra-ticket charge, never both for the same event. These
are fictional policy fixtures, not active coverage, insurance or a promise that
a production claim would be automatic or immediate. The successful path closes
coverage immediately after its simulated delivery check; a production policy
would retain capacity through its defined claim window.

Every new walkthrough receives its own seeded 1,000-USDC sandbox reserve. The
MVP therefore demonstrates one order's accounting and idempotency, not portfolio-wide
capital adequacy or concurrent admission against one shared reserve.

## What is implemented

- A versioned `belay.purchase.v0.3` run schema with stable grant, order,
  operation, case and provider identities.
- Persistent application, provider, account, coverage, ledger and claim records
  in local SQLite databases.
- Exact deterministic policy checks in `purchase_simulator/policy.py`.
- A persisted order-authority record that freezes the admitted grant, offer,
  quote, amount and beneficiary before signing or dispatch.
- An independent local payout fixture in `purchase_simulator/provider.py` with
  one record per operation and read-only lost-reply reconciliation.
- Exact provider-response validation plus a persisted settlement record binding
  both assets, both amounts, beneficiary, intent digest and provider reference.
- Atomic local admission of the customer hold and protection commitment.
- Separate funding, conversion, payout, order, delivery and protection states.
- Expected-revision checks that stop stale or overlapping browser actions from
  advancing the same run twice.
- A unified fictional receipt for completed purchases and remedies.
- Per-event customer messages, state snapshots, balance deltas, provider
  observations, ledger keys and technical explanations that drive both UI panes.

## Architecture boundaries

The local state machine demonstrates how the proposed components fit together;
it is not the production payment protocol. The `belay://` and `.invalid` trace
routes are descriptive and never contacted. The provider does not convert a
token, perform KYC/AML checks or send a bank payment. The reserve is a seeded
SQLite balance rather than safeguarded or insured capital. Delivery evidence is
constructed data, not an authenticated ticket issuer or customer device report.

The deterministic executor is a logical boundary within one Python process. It
is not a smart contract, HSM, custodian, money transmitter or licensed payout
service. The authorization object uses a `mocksig` value and a fake key
reference. Private keys never appear because the demo has none. The shopping
agent is scripted fixture behavior and this repository does not connect the
conversation's language model to the app.

The simulator remains isolated from the research runtime, the legacy Recovery
Lab and the teammate Recovery Desk work. It does not alter their journals,
databases or reported experiment results. The broader live architecture still
requires reviewed contracts, provider approval, authenticated users, custody
and compliance decisions, real evidence adapters, funded terms and operational
controls.

## Verify

```bash
python -m unittest discover -s tests -p "test_purchase_simulator.py" -v
node --check purchase_simulator/web/app.js
node --test tests/test_purchase_simulator_ui.mjs
```

The Python suite uses temporary databases and no remote services. It checks the
scenario outcomes, asset conservation, reserve accounting, policy rejection,
stable-operation recovery, duplicate claim prevention, persisted schema and
loopback HTTP boundary. CI runs it on Windows and Linux.

## Local API

| Route | Body | Purpose |
|---|---|---|
| `GET /api/config` | — | Read schema version, scenarios, assumptions and fictional credentials |
| `POST /api/runs` | `scenario`, integer `budget_cents`, `quantity: 2` | Create a bounded fictional mission; the cents-shaped input is projected to six-decimal demo USDC units |
| `GET /api/runs/{id}` | — | Read the persisted run, separate balances, provider observation, claims and trace |
| `POST /api/runs/{id}/advance` | integer `expected_revision` | Execute one permitted transition |
| `POST /api/runs/{id}/verify` | integer `expected_revision` | Compatibility route from the earlier card demo; v0.3 has no bank challenge and returns HTTP 409 without changing the run |

A stale revision returns HTTP 409 with the current run in `current`. The UI
pauses after an HTTP failure and never treats a missing reply as proof that a
payout failed.
