# Belay Recovery Lab

Belay helps an agent recover an external action without silently replacing
the original intent or guessing whether the action happened. The payment
provider executes the refund; Belay records and reconciles it.

## Run locally

From a repository checkout, with Python 3.10 or newer:

```bash
python -m prototype.server --port 8765 --data-dir .belay-prototype
```

Open **http://127.0.0.1:8765**. The app binds to loopback only. Keep the
terminal running while using it. Restart with the same data directory to
retain previous cases. No API keys, account setup, model service, payment
account, package installation or frontend build is required.

The backend and UI are the first two product surfaces:

- **Recovery Lab:** run an action, observe a crash, and recover it. Inspect
  the actual local API request, frozen intent and independent provider ledger.
- **Activity:** reopen persisted cases and inspect the evidence and outcome.
  Blocked cases remain unresolved; there is no button that pretends an
  operator can establish a missing fact without provider evidence.

## A two-minute walkthrough

1. Choose **Payment sent. Receipt not saved.**, select **With Belay**, then **Run
   experiment**. The provider paid $50, but the worker did not save a receipt.
2. Select **Recover this case**. Belay looks up the original operation and
   records its existing receipt. The provider total remains $50.
3. Select **Unprotected retry** and run a new experiment. On recovery, the
   scripted agent chooses a $30 refund with a fresh key. The provider now
   records $80 against that case's $100 order: $30 beyond the original intent.
4. Run **Provider's safe retry**. It reuses the original $50 request and
   key. It also finishes with $50. This illustrates what existing provider
   idempotency already solves, rather than attributing that capability
   exclusively to Belay.
5. Try **Provider cannot confirm** with Belay. The observer can see the
   provider ledger, but the recovering worker cannot query that provider.
   It stops with an unresolved case instead of issuing another refund.

## Scenarios

| Scenario | Initial state | Belay recovery |
|---|---|---|
| `clean` | Intent and receipt saved | Already complete; no new action |
| `lost_ack` | Provider committed, local receipt missing | Query original reference and recover its receipt |
| `before_send` | Intent saved, no provider request | Provider establishes absence; check permission and send original intent |
| `revoked` | Stops before sending; permission then withdrawn | Refuse to create a new refund |
| `opaque` | Provider committed but offers no lookup or dedupe | Keep unknown outcome blocked |

All amounts use integer cents. Every case has a fictional $100 order and
an intended $50 partial refund. The changed $30 decision is scripted to
make the failure deterministic; it is not measured model behavior.

## What really runs

The application exposes a small local JSON API:

```text
GET  /api/cases
POST /api/cases                  {"mode":"belay","scenario":"lost_ack"}
GET  /api/cases/<id>
POST /api/cases/<id>/recover      {}
```

The worker communicates with a local mock payment provider over HTTP. The
application's durable state and the provider's ledger live in separate
SQLite databases. The provider can commit even when the client never saves
its receipt. The console reads independent provider evidence for the human
observer; opaque-provider recovery does not gain access to that evidence.

For the crash scenarios a subprocess exits abruptly through `os._exit`.
It does not unwind Python `finally` blocks. In `lost_ack`, the worker has
received the HTTP receipt but exits before saving it; the missing durable
receipt is real, while no network packet loss is injected. The application
process performs reconciliation from persisted state, and a new worker
process submits an action when needed. This portable demonstration is
distinct from the repository's POSIX SIGKILL experiments and does not
independently reproduce their results.

Requests are serialized in one running application process. That makes
repeated clicks safe in the local demonstration; it is not a distributed
lease or a multi-instance deployment design. Use one server per data
directory. This development server is intended for local use only.

## Provider assumptions and unfinished work

The fictional provider commits synchronously, is honest, retains keys
permanently and gives authoritative lookup results. In production, an
ordinary "not found" response can coexist with a pending request that
later commits. A real adapter must distinguish committed, definitively
absent, pending and unknown, and must respect key expiration. It must also
validate the receipt against the original operation and permission rules.

The prototype does not detect fraud, judge whether the initial refund was
appropriate, insure losses, recover arbitrary sellers' payments, or claim
universal exactly-once execution. It has no live payment integration,
multi-tenant access control, distributed concurrency mechanism or evaluation
of real model decisions. Fresh permission checks do not make a provider
commit atomic with a permission revocation.

Before a live pilot: fix the original runtime issues listed in REVIEW.md,
choose one provider and one existing agent framework, establish the
provider's recovery contract, test pending and expired-key outcomes, and
compare the integration with the customer's correct stable-key baseline.

## Verification

```bash
python -m unittest discover -s tests -p "test_prototype.py" -v
python experiments/check_docs.py
ruff check .
```

The portable suite is separate from `tests/test_contract.py`. Run the
original contract suite on Linux, macOS or WSL; a Windows prototype pass
does not establish a POSIX SIGKILL contract pass.
