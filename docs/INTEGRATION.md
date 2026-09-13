# Repository integration guide

## What works together today

The repository combines a portable local Recovery Lab, the recorded Recovery
Desk, the research evidence adjudicator and the live decision experiments.
All components are checked in the same CI workflow. The lab is a separate
implementation of the recovery pattern; it is not a production adapter around
the research runtime.

| Component | Entry point | State and boundary |
|---|---|---|
| Research runtime | `worker.py`, `belay/runtimes/anchored.py` | Research journal, permission store and synthetic services; POSIX crash experiments |
| Evidence adjudicator | `second/adjudicate.py`, `second/apply.py` | Research dossiers and evidence; may complete a verified absent effect through a callback |
| Recovery Desk | `experiments/recovery_demo.py`, `viewer/build_viewer.py` | Recorded POSIX crash scenarios using the research runtime and adjudicator; browser controls only inspect recordings |
| Optional recovery model | `second/live_agent.py` | OpenAI proposes evidence pointers and claims; deterministic validation and the guarded executor retain control |
| Live decision experiment | `experiments/run_live_agent.py` | Optional API-backed measurement and committed results; not the lab's decision engine |
| Recovery Lab | `python -m prototype.server` | Separate SQLite application/provider stores and loopback HTTP; scripted decisions and fictional money |
| Purchase Simulator | `python -m purchase_simulator.server` | Separate local application/provider records; interactive ticket purchase, permission checks, mock credentials and exact-operation recovery |
| Autonomous app and guarantee | Architecture and proposal documents | Future services; no live purchases, subscriptions, coverage or reimbursements |

Keep lab data under `.belay-prototype/` or another isolated directory. Do not
point it at research evidence or treat its database as the JSONL research
journal. Preserve committed `results/` when validating documentation; they
are research evidence rather than application state.

The Purchase Simulator uses `.belay-purchase-simulator/` and port 8777, with
no imports from the research or Recovery Lab execution engines. It demonstrates
the proposed purchase boundary without changing those engines or their stores.
Its internal mock-service calls are displayed as fictional API traces; only
browser-to-loopback requests are actual HTTP. The records are deliberately
simplified and are not AP2 schema implementations. See
[PURCHASE_SIMULATOR.md](PURCHASE_SIMULATOR.md) for scenarios and limitations.

## Run and test

From a clone with Python 3.10 or newer:

```bash
python -m prototype.server --port 8765
python -m unittest discover -s tests -p "test_prototype.py" -v
python tests/test_evidence_boundaries.py
python tests/test_live_agent.py
python tests/test_evaluate_recovery.py
python experiments/check_docs.py
```

The server binds to `127.0.0.1`; it is a local development demonstration.
Use one server per lab data directory. No external payment credentials are
needed. The prototype runs from a clone; the existing distribution described
by `pyproject.toml` does not package the lab or its web assets.

On POSIX with Make available, `make prototype` starts the lab,
`make test-prototype` runs its tests, and `make all` includes both the lab and
recovery suites alongside the existing research checks. `make test-evidence`
runs portable order/source isolation regressions. `make test-recovery` also
runs the adapter, evaluation and recorded demo checks. `make test` and `make test-second`
remain the research contract and evidence-adjudicator suites. The full crash
and adjudication experiments require POSIX. CI tests the lab on Windows and
Linux and the research suites on Linux and macOS.

Use `make recovery-demo` on POSIX to record the Recovery Desk, then open
`viewer/trace.html`. See [DEMO.md](DEMO.md) for the optional model and
`make evaluate-recovery` for an offline comparison. The model never receives
payment credentials or an execution callback.

CI checks committed results against documentation before experiments run.
It then asserts the fresh results and uploads those same results with the
standalone viewer. Do not restore committed results before these assertions
or the artifact upload.

The shared evidence store restricts sources to files inside its evidence root.
The recovery adapter restricts pointers to advertised sources, their manifests
and exact current-order selectors. Absence validation requires the exact order identity;
a similarly prefixed order is not evidence for the current action. Reapplying
a dossier also requires its bound journal state to remain current.

## Boundary for the proposed autonomous app

The future app should expose one controlled action submission boundary. The
planner supplies a proposal; the authority service validates it and the
executor records and performs the permitted operation. This is an extension
contract, not an implemented API in the current lab.

The record passed across that boundary must retain:

- User, mission and stable operation identity, kept separate from a provider's
  request/receipt identifiers.
- Grant version, allowed action, provider and credential reference.
- Exact immutable intent, quote/version/hash, amount and currency.
- Reserved budget, submission status and verified provider evidence.

An adapter declares its actual capabilities and retry rules. A success response
needs evidence tied to the original operation and exact inputs. A failed
connection or empty lookup does not automatically establish absence. Provider
idempotency scope and lifetime must be respected across restarts.

Do not make both the model and an adjudicator independent executors. If
`second/` is adapted, read validated findings through a reviewed translation
layer. Keep its production completion callback behind the same authority,
budget, intent and idempotency controls. Do not expose `apply_dossier` with
an unrestricted payment callback to the app's agent.

Research evidence fixtures are not authenticated merchant reports. Any
production evidence adapter must establish source identity, integrity,
completeness and freshness, then bind the observation to the correct
operation. A correct research verdict does not establish live bank authority.

## Boundary for a guarantee

Provider recovery and customer compensation use different authorizations.
The recovery service reconciles orders/payments and requests available
remedies. The claims service reads that evidence and the customer's active
terms, calculates eligible unrecovered loss and sends the claim to its
designated decision maker and payer. Its payout record must not be confused
with the original purchase or merchant refund.

The purchasing model cannot approve its own reimbursement. Use distinct
claim and payout IDs, deduplicate retries and account for refunds already
received. The current research adjudicator does not supply subscription
entitlement, financial-loss assessment, insurance authority or claim funding.

## Migration gates

Before calling a future integration ready, demonstrate policy rejection,
concurrent budget reservation, expired/revoked authority, provider challenges,
crash recovery, delayed evidence and duplicate callbacks with the chosen
provider. Preserve unknown outcomes when evidence is insufficient. Verify
the exact adapter and payment/mandate profile; do not infer compatibility
from similar names or fields.

Known original-runtime defects remain documented in [REVIEW.md](REVIEW.md).
Neither the separate lab suite nor an architectural diagram proves that
the research runtime or a future live app is production-ready.
