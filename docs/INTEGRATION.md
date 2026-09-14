# Repository integration guide

The main demonstration is now the local **Belay Recovery Desk**, an operator
application using the same JSONL journal and evidence adjudicator as the
research work. It creates an incident, investigates the available records,
shows a supported resolution or the evidence still needed, and records the
operator's guarded resolution.

## Components and boundaries

| Component | Entry point | Actual behavior |
|---|---|---|
| Local Recovery Desk | `python -m recovery_app.server` | Persistent incidents, research JSONL journal, `second/` validation, evidence refresh, current permission checks and downloadable audit receipts. |
| Optional model | `second/live_agent.py` | OpenAI proposes pointers and a cited verdict; the validator determines support and the operator applies an eligible result. |
| Local refund provider | `services/ledger.py` through `recovery_app/engine.py` | SQLite simulation with fictional amounts. Constructed interrupted states; creating an app incident does not kill a process. |
| Arc Testnet evidence | `recovery_app/arc.py` and browser wallet adapter | A person signs a capped test-USDC transfer in MetaMask. The server only reads the original transaction and verifies its receipt against persisted intent. |
| Research runtime | `worker.py`, `belay/runtimes/anchored.py` | Journal, permission store, simulated external services and POSIX SIGKILL experiments. |
| Recorded Recovery Desk | `experiments/recovery_demo.py`, `viewer/build_viewer.py` | Saved real-crash demonstrations; browser controls inspect a recording. |
| GitHub Pages | `site/`, `scripts/build_site.py` | Static product introduction and recordings. It does not host the Python API or contain model credentials. |
| Legacy Recovery Lab | `python -m prototype.server` | Separate SQLite implementation retained for the earlier baseline comparison. Its database is not a research journal. |
| Autonomous purchasing and guarantee | Architecture/proposal documents | Future ideas; no ticket booking, subscriptions, banking, insurance or reimbursement service. |

## Run locally

From a clone with Python 3.10 or newer:

```bash
python -m recovery_app.server --port 8766
```

Open `http://127.0.0.1:8766`. The deterministic baseline works without a
wallet, credentials or network. Application data defaults to
`.belay-recovery/`; use `--data-dir` for an isolated demonstration.
One process owns each directory, and mutation calls are serialized.
This loopback development server is not an authenticated hosted service.

Set `OPENAI_API_KEY` and an explicit `OPENAI_MODEL` in the server environment
to enable the optional model. Do not put either in browser code or commit
the key. Each investigation permits at most two model requests and no
automatic retries. Model requests can incur charges; the offline baseline
does not make them. The model receives the bounded case view and requested
evidence, never a signing key, payment credential or execution callback.

The portable checks and evaluations are:

```bash
python tests/test_evidence_boundaries.py
python tests/test_live_agent.py
python tests/test_evaluate_recovery.py
python tests/test_recovery_holdout.py
python experiments/evaluate_recovery.py --audit-unvalidated --out tmp-runs/recovery-evaluation.json
python experiments/recovery_holdout.py --out tmp-runs/recovery-holdout.json
python experiments/check_docs.py
```

The raw-claim audit is classification only: it never executes an unvalidated
dossier. For an optional model comparison use
`python experiments/evaluate_recovery.py --agent openai --model MODEL_ID`.
Both agents receive identical isolated cases and evidence limits; the
heuristic uses no model tokens. This is not an equal-compute comparison.

The full research contract and recorded crash demo require POSIX signals:
run them on Linux, macOS or WSL. Preserve committed `results/` while testing;
the commands above write new reports under `tmp-runs/`.

## Evidence and authority

The source store allows only files within its configured root. The model
can request at most 16 pointers. A deterministic consistency scan covers
at most eight advertised sources, with a manifest and exact-order query
for each. Each source is limited to 1 MiB and 1,000 records. Exceeding a
bound or encountering unreadable evidence yields abstention.

Every cited observation must have actually been fetched for the model.
Additional context can reject selective or contradictory conclusions but
cannot provide missing support on the model's behalf. Matching committed
records conflict with complete covered silence; inconsistent amounts,
source identities, simulator effect IDs or same-chain transaction hashes
also block resolution. The scan does not decide which conflicting source
is true. Local file provenance and declared coverage remain assumptions,
not Byzantine consensus or authenticated merchant attestations.

Applying a dossier requires the current halted journal revision and original
intent. The app also invalidates proposals after its evidence snapshot
changes. Reporting an established commitment issues no effect. Completing
a verified absent local refund checks current permission immediately before
the simulated call. A failure after the durable application intent requires
fresh adjudication.

## Test-wallet demonstration

Belay has no custodial wallet or balance of its own. MetaMask holds the
user-controlled signing key; Belay only stores public addresses, the exact
test transfer intent and a transaction hash. The integration is fixed to Arc
Testnet, chain ID `5042002`, and Circle's test-USDC token. Amounts are limited
to 0.01–1.00 test USDC in 0.01 increments.

Use two test accounts and the faucet linked from the app. Faucet availability,
rate limits and network access are external prerequisites. No real funds are
needed, but a faucet balance is needed for the transfer and test gas.
The wallet confirmation belongs to the person holding the key; neither the
server nor the model signs or broadcasts a replacement transfer.
Follow [the test-wallet setup guide](TEST_WALLET.md) for the actual browser steps.

A confirmed outcome requires the correct chain, token, sender, recipient,
amount, original transaction, successful Transfer event and the adapter's
canonical finalized-block checks. A missing, pending, failed or inconsistent
receipt cannot authorize another transfer. The RPC node and network consensus
remain trust assumptions; this is not a light-client proof. Transaction hashes
remain strings, separate from integer IDs in the local payment simulator.

The downloadable receipt is a local audit record of the evidence and decision.
It is not a cryptographic guarantee of external truth, a refund promise or
insurance coverage.

## Production work remains

[REVIEW.md](REVIEW.md) distinguishes fixed defects from open limitations.
A real deployment still needs authenticated users, reviewed provider-specific
authority and finality semantics, deployment migration rules, operational
monitoring and a concurrency model appropriate to its storage. Any future
payout or guarantee service requires separate authority and funding; the
recovery model must never approve its own compensation.
