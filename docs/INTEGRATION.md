# Repository integration guide

Belay has two current local applications with separate responsibilities. The
**Payment Mission MVP** prepares, authorizes and simulates one exact payment.
The **Recovery Desk**, merged in PR #10, investigates an interrupted action and
records what the available evidence supports. They do not share a database.
Both generalized missions and the ticket walkthrough call the shared read-only
payment investigator in `recovery_app/payment.py` through distinct typed intent
adapters. They reuse its evidence checks in process; running the separate
Recovery Desk HTTP server is optional.

The AI Apps pitch follows one thread: authorize an exact action, then explain
and safely recover an uncertain outcome. Payment Mission is its commerce
interface; Recovery Desk supplies the evidence boundary, optional model and
human-signed Arc Testnet demonstration. See the
[PR #10 integration record](PR10_PAYMENT_REVIEW.md).

## Components and boundaries

| Component | Entry point | Actual behavior |
|---|---|---|
| Payment Mission MVP | `python -m purchase_simulator.server` | Plain-language draft, editable plan, one exact authorization, deterministic checks, simulated USDC-to-USD payout, scoped receipt and synchronized customer/backend views |
| Legacy protected-purchase API | `/api/runs` on the Payment Mission server | Ticket-specific local state machine, reserve accounting and claims; saves dispatch uncertainty before provider I/O and retains the payment hold while acceptance may be unknown |
| Legacy purchase recovery bridge | `purchase_simulator/recovery.py`, `recovery_app/purchase.py` | Binds the exact v0.3 purchase intent to read-only provider evidence and returns `paid`, `unknown` or `conflict`; it cannot send or release money |
| Mission recovery bridge | `purchase_simulator/mission_recovery.py`, `recovery_app/payment.py` | Binds an exact general payment without fabricated order or refund identities; read-only findings precede explicit reconciliation under the original operation |
| Local Recovery Desk | `python -m recovery_app.server` | Persistent incidents, research JSONL journal, `second/` validation, evidence refresh, current permission checks and downloadable audit receipts |
| Optional recovery model | `second/live_agent.py` | OpenAI proposes pointers and a cited verdict; deterministic validation decides support and the operator applies an eligible result |
| Local refund provider | `services/ledger.py` through `recovery_app/engine.py` | SQLite simulation with fictional amounts and constructed interrupted states |
| Arc Testnet evidence | `recovery_app/arc.py` and browser wallet adapter | A person signs a capped test-USDC transfer in MetaMask; the server reads and verifies the original receipt against persisted intent |
| Research runtime | `worker.py`, `belay/runtimes/anchored.py` | Journal, permission store, simulated services and POSIX SIGKILL experiments |
| Recorded Recovery Desk | `experiments/recovery_demo.py`, `viewer/build_viewer.py` | Saved real-crash demonstrations; browser controls inspect a recording |
| GitHub Pages | `site/`, `scripts/build_site.py` | Static product introduction and recordings; it does not host either Python API |
| Legacy Recovery Lab | `python -m prototype.server` | Earlier separate SQLite implementation retained for baseline comparison |
| Live payment and guarantee services | Architecture documents | Future custody, settlement, payee, compliance and funded-remedy work |

## Run Payment Mission

From a clone with Python 3.10 or newer:

```bash
python -m purchase_simulator.server --port 8777
```

Open `http://127.0.0.1:8777`. Its default data directory is
`.belay-purchase-simulator/`; the Windows launcher uses the isolated
`mission-v1/` subdirectory. The browser makes real loopback HTTP requests and
the server persists missions, revisions, events, unique ledger movements and
fictional provider results in SQLite. The preserved seven-scenario purchase
walkthrough is available at `http://127.0.0.1:8777/purchase/`.

The Python distribution includes `purchase_simulator`, `recovery_app`, both
applications' web assets, the preserved purchase walkthrough, and the
installed `belay-mission` command. No API key or third-party dependency is
needed. Use one server process per data directory.

Verify the current and compatibility paths with:

```bash
python -m unittest discover -s tests -p "test_mission_control.py" -v
python -m unittest discover -s tests -p "test_mission_inputs.py" -v
python -m unittest discover -s tests -p "test_mission_recovery.py" -v
python -m unittest discover -s tests -p "test_purchase_simulator.py" -v
python -m unittest discover -s tests -p "test_purchase_recovery.py" -v
node --check purchase_simulator/web/app.js
node --test tests/test_purchase_simulator_ui.mjs tests/test_purchase_walkthrough_ui.mjs
```

The Payment Mission extractor, signature, wallet, USDC, conversion, bank payout
and payee confirmation are local fixtures. No model, chain, custodian, bank,
government agency, biller, insurer or merchant is connected. The app never
accepts a private key or raw payment credential.

## Run Recovery Desk

```bash
python -m recovery_app.server --port 8766
```

Open `http://127.0.0.1:8766`. The deterministic baseline works without a
wallet, credentials or network. Application data defaults to
`.belay-recovery/`; use `--data-dir` for an isolated demonstration. One process
owns each directory and mutation calls are serialized. This loopback server is
not an authenticated hosted service.

Set `OPENAI_API_KEY` and an explicit `OPENAI_MODEL` in the server environment
to enable the optional model. Do not put either in browser code or commit the
key. Each investigation permits at most two model requests and no automatic
retries. The model receives the bounded case view and requested evidence,
never a signing key, payment credential or execution callback.

The portable checks and evaluations are:

```bash
python tests/test_recovery_app.py
python tests/test_arc.py
python tests/test_evidence_boundaries.py
python tests/test_live_agent.py
python tests/test_evaluate_recovery.py
python tests/test_recovery_holdout.py
python tests/test_operator_export.py
python experiments/evaluate_recovery.py --audit-unvalidated --out tmp-runs/recovery-evaluation.json
python experiments/recovery_holdout.py --out tmp-runs/recovery-holdout.json
python experiments/check_docs.py
```

Run the JavaScript tests with Node rather than Python:

```bash
node --test tests/test_recovery_app_ui.mjs tests/test_wallet_ui.mjs
```

The raw-claim audit is classification only: it never executes an unvalidated
dossier. For an optional model comparison, use
`python experiments/evaluate_recovery.py --agent openai --model MODEL_ID`.
Both agents receive identical isolated cases and evidence limits; the heuristic
uses no model tokens. This is not an equal-compute comparison.

The full research contract and recorded crash demo require POSIX signals. Run
them on Linux, macOS or WSL. Preserve committed `results/` while testing; the
commands above write new reports under `tmp-runs/`.

## How the payment path works

The `belay.mission.v0.1` record keeps the original request, editable plan,
bounded grant, deterministic policy result, signed-intent digest, event stream,
single-use ledger keys, provider payout and scoped receipt. Customer USDC, the
payment hold, provider transit and payee USD remain separate balances.

The implemented path is:

```text
request -> reviewed plan -> exact authorization -> deterministic checks
        -> USDC hold -> bound instruction -> simulated USD payout -> receipt
```

Enable **Simulate a lost payout reply** to exercise the uncertain path. The
fictional provider records payment while local accounting remains in transit.
Investigation reads the original operation without mutating the mission.
Explicit reconciliation checks the current revision, saved intent, fresh
provider evidence and its digest before accounting the original payout once.
Missing, incomplete or contradictory evidence never releases funds or permits
another send. The local provider and mission use SQLite; this demonstrates the
recovery contract, not an external-provider crash protocol.

The customer and backend views are projections of the same persisted event.
Expected-revision checks reject stale actions. Unique ledger keys and one
stable operation identity prevent a repeated local transition from moving the
same value again. The older `belay.purchase.v0.3` ticket API uses separate
tables and does not drive the current interface.

## Legacy v0.3 recovery bridge

Commit `fe23651` connects the legacy ticket simulator's lost-payout path to a
typed, read-only investigator. Before provider I/O, `dispatch_attempts_v3`
durably binds the run, mission, order, operation and canonical intent. Once
dispatch may have started, cancellation or expiry cannot release the order
hold merely because a provider reply is missing.

`POST /api/runs/{id}/investigate` accepts only the exact current
`expected_revision`. It looks up the original operation and returns evidence,
never an execution token. `PurchaseIntent` binds the grant digest,
beneficiary, six-decimal USDC base units, USD cents and canonical intent. An
unavailable lookup, missing record, partial status or malformed evidence stays
`unknown`; mismatched identity or value becomes `conflict`. Only exact paid
evidence sets `can_reconcile`.

The legacy executor then reads the provider again and requires the evidence
digest to remain current before it accounts the original payout once. It never
accepts a browser-supplied verdict and never submits a replacement through the
investigation route. Delivery, refunds and claims remain separate operations.
This adapter covers `belay.purchase.v0.3`. Generalized `belay.mission.v0.1`
uses its own typed adapter over the same payment-evidence validator. The ticket
API and its `/purchase/` interface retain their existing lifecycle.

The receipt states its evidence boundary. Payment does not prove delivery, tax
filing, a remaining bill balance, insurance coverage or claim approval. A live
payee-domain adapter must provide authoritative acceptance evidence before
Belay can report those outcomes.

## Recovery evidence and authority

The Recovery Desk source store allows only files within its configured root.
The model can request at most 16 pointers. A deterministic consistency scan
covers at most eight advertised sources, with a manifest and exact-order query
for each. Each source is limited to 1 MiB and 1,000 records. Exceeding a bound
or encountering unreadable evidence yields abstention.

Every cited observation must have been fetched for the model. Additional
context can reject selective or contradictory conclusions, but cannot provide
missing support on the model's behalf. Matching committed records conflict
with complete covered silence; inconsistent amounts, source identities,
simulator effect IDs or same-chain transaction hashes also block resolution.
The scan does not decide which conflicting source is true. Local file
provenance and declared coverage remain assumptions, not Byzantine consensus
or authenticated merchant attestations.

Applying a dossier requires the current halted journal revision and original
intent. The app invalidates proposals after its evidence snapshot changes.
Reporting an established commitment issues no effect. Completing a verified
absent local refund checks current permission immediately before the simulated
call. A failure after durable application intent requires fresh adjudication.

PR #10's pre-merge verified-failure dead end was fixed in `250456f`. A
canonical finalized failed Arc transaction can now close as a failed outcome
without being treated as a successful transfer or authorizing an automatic
retry.

## Arc test-wallet demonstration

Belay has no custodial wallet or balance of its own. MetaMask holds the
user-controlled signing key. Belay stores only public addresses, the exact test
transfer intent and a transaction hash. The integration is fixed to Arc
Testnet, chain ID `5042002`, and Circle's test-USDC token. Amounts are limited
to 0.01–1.00 test USDC in 0.01 increments.

Use two test accounts and the faucet linked from the app. Faucet availability,
rate limits and network access are external prerequisites. No real funds are
needed, but a faucet balance is needed for the transfer and test gas. The
wallet confirmation belongs to the person holding the key; neither the server
nor the model signs or broadcasts a replacement transfer. Follow the
[test-wallet setup guide](TEST_WALLET.md).

A confirmed outcome requires the correct chain, token, sender, recipient,
amount, original transaction, successful Transfer event and the adapter's
canonical finalized-block checks. A missing, pending, failed or inconsistent
receipt cannot authorize another transfer. The RPC node and network consensus
remain trust assumptions; this is not a light-client proof. Transaction hashes
remain strings, separate from integer identities in the Payment Mission MVP.

The downloadable receipt is a local audit record of the evidence and decision.
It is not a cryptographic guarantee of external truth, a refund promise or
insurance coverage.

## Safe integration contract

For `belay.mission.v0.1`, Recovery Desk remains a read-only observer invoked
through the mission's typed adapter. The `belay.purchase.v0.3` bridge uses the
same checks under its distinct purchase intent. Both providers are fictional;
neither adapter proves compatibility with a live provider. Do not expose a resolution
callback to the purchasing agent. Do not relabel Arc Testnet receipts as Base
payments: chain IDs, token addresses, gas and finality rules are different.

A future adapter record must retain:

- user, mission and stable operation identity;
- grant version, exact immutable intent, amount, asset and beneficiary;
- provider request, receipt and reconciliation identities;
- chain, token, decimals, transaction lineage and observed finality when used;
- payee-domain evidence and its source, freshness and meaning; and
- any claim, recovery and payout identities separate from the purchase.

An empty lookup or failed connection does not establish that a payment is
absent. Provider idempotency scope and lifetime must survive restarts. Chain
receipt arrival is not finality, and removed events must be unwound after a
reorganization.

## Production work remains

A real payment deployment needs authenticated users, production key custody,
reviewed custody and money-transmission roles, provider-specific authority and
finality semantics, a regulated USDC-to-USD settlement route, verified payee
adapters, compliance controls, deployment migration rules, monitoring and an
appropriate concurrency model.

Any payout guarantee requires separate authority, terms and funding. The
purchasing model and recovery model cannot approve their own compensation.
The local payment simulation, Arc test-wallet receipt and research evidence
fixtures do not establish merchant delivery, tax filing, insurance coverage,
customer demand, production safety or provider approval. See
[REVIEW.md](REVIEW.md) for fixed defects and remaining limitations.
