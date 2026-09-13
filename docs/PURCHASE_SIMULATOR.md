# Belay purchase simulator

This local app puts the customer experience beside the backend execution of
one fictional concert-ticket purchase. It turns the proposed Belay workflow
into a step-through demonstration with inspectable requests, demo credentials,
separate order/payment/delivery states and a provider record that survives
an intentionally lost reply.

## Run

From a repository clone with Python 3.10 or newer:

```bash
python -m purchase_simulator.server --port 8777
```

Open `http://127.0.0.1:8777`. No installation, API key, model account or payment
account is needed. The server listens on loopback only. Use a single server
process per data directory. This source-tree application is not included in
the existing Python distribution, matching the Recovery Lab packaging boundary.

The application stores its state under `.belay-purchase-simulator/`, separate
from the Recovery Lab and research evidence. To use another isolated data
directory, pass `--data-dir PATH`. Reloading the browser resumes its most
recent run if browser storage is available. Restarting the server with the same
data directory preserves the run and simulated provider records. Playback
does not automatically resume after a reload.

## Follow both sides

1. Choose a scenario and a total budget. The default mission is two adjacent
   tickets for The Midnight Signals at Harbor Hall, Boston, on October 24,
   2026 at 8 PM, from the fictional Northstar Tickets merchant.
2. Click **Authorize mission**. This is the initial bounded approval. The
   fixture's grant supplies a fixed event, seller, quantity and expiry.
3. Use **Next step** to inspect the sequence or **Play through** for timed
   playback. The left panel shows what the customer hears; the right shows
   the current backend event and ledger state.
4. Open **Demo credentials** to inspect the invented API credentials and
   protected-key reference. Use **Request / Response** and **Inspect a step**
   to read each event's payload and explanation.
5. Playback pauses on an unknown outcome or bank challenge. Reconciliation
   is a deliberate next step; verification requires the customer-view button.
6. After a completed or blocked run, **New simulation** starts an independent
   demo mission. It does not erase the previous server records or refund it.

Each grant lasts 30 minutes. The simulator checks expiry before signing,
token release, checkout submission and bank verification. A submitted purchase
may still finish, and read-only recovery remains possible, after that deadline.
An expired bank challenge stays pending with its reservation held; this demo
does not implement mission renewal or cancellation of that pending operation.

## Scenarios

| Scenario | What happens | Expected result |
|---|---|---|
| Successful purchase | A $280 offer satisfies a $300 mission | One provider capture, $280 confirmed spend and two demo tickets |
| Merchant reply is lost | Provider capture succeeds, but the checkout response is withheld | Belay keeps the reservation, reports unknown status, then reconciles the exact operation without a second capture |
| Offer exceeds your budget | Seller returns $320; the default mission allows $300 | Purchase stops at the permission check before token release or payment; a larger explicitly approved budget can allow the offer |
| Bank asks for verification | The issuer requires a challenge | Execution pauses with no capture until simulated verification completes |
| Bank declines | Authorization is rejected | No capture or ticket delivery; reserved budget is released |

**Budget reserved** is the amount unavailable to another action within this
mission; it does not itself move money. **Confirmed spent** is what Belay has
confirmed. **Provider captures** is the simulator's observer view of the
provider's actual local records. In the lost-reply state that counter is one
while Belay's confirmed spending remains zero and its reservation stays held.
The agent does not receive that observer counter as a shortcut to recovery.

The UI permits one active run at a time. Budgets and grants are isolated per
mission; this is not a shared wallet across browser tabs, users or subscriptions.

## What is real and what is simulated

The browser makes actual HTTP requests to the local Python server. That
server executes the checks and advances durable state, rather than animating
a canned screenshot. A stable operation identity ties the intended purchase,
provider record and recovery lookup together. An expected revision prevents
repeated or overlapping step requests from executing an action twice.

Merchant, credential-provider, payment-processor and issuer calls are local
mock functions. Their trace URLs end in `.invalid` and are never contacted.
The API keys, card references, tokens, agent decisions and signature markers
are fictional. They do not implement cryptographic authorization, PCI
compliance, an AP2 schema, a real wallet or live payments. Both initial and
transaction-bound authority are represented with simplified demo records.

The protected executor is a logical boundary inside one process, not a
production security boundary or a hardware-backed key store. The demo exposes
fixture credentials intentionally; real private keys and raw payment data
would not appear in a developer panel or a model context.

This simulation demonstrates the flow on top of the existing
[autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md). It does not
wrap the research runtime or Recovery Lab. Their tests and data retain their
existing meanings. No blockchain, guarantee payout, refund execution,
subscription, merchant account or bank access is added.

The lost reply is deliberately injected. Its provider is cooperative and can
return a definitive record for the exact operation. The demo does not establish
recovery from every process crash or model production provider consistency,
chargebacks, delayed settlement, real ticket fulfillment or multi-process
concurrency. Production adapters must declare those capabilities independently.

## Verify

```bash
python -m unittest discover -s tests -p "test_purchase_simulator.py" -v
node --check purchase_simulator/web/app.js
```

The suite checks purchase outcomes, persistent state, reconciliation without
duplicate capture, cap rejection before spending, mandatory bank verification,
stale/concurrent step requests and loopback HTTP validation. It uses temporary
databases and no remote services. The existing portable CI matrix runs these
tests on Windows and Linux alongside the Recovery Lab tests.

## Local API

| Route | Body | Purpose |
|---|---|---|
| `GET /api/config` | — | Scenarios and fictional credentials |
| `POST /api/runs` | `scenario`, integer `budget_cents`, `quantity: 2` | Approve and create a bounded demo mission |
| `GET /api/runs/{id}` | — | Read the persisted run and trace |
| `POST /api/runs/{id}/advance` | integer `expected_revision` | Execute one permitted transition |
| `POST /api/runs/{id}/verify` | integer `expected_revision` | Complete the simulated issuer challenge |

A stale revision returns HTTP 409 with the current run in `current`. Unknown
outcomes retain their operation identity. The UI pauses on an HTTP failure;
it does not automatically resend a purchase or assume the prior request failed.
