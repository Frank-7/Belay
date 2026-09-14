# Repository integration guide

For the teammate's draft Recovery Desk and Arc Testnet increment, see
[PR #10 payment review](PR10_PAYMENT_REVIEW.md). It is compatible with current
main at `cffe7ac` but conflicts with this simulator branch in seven shared
build/documentation files. Keep its read-only chain recovery separate from the
proposed protected executor, USD payout and compensation modules. Its refund
slot schema needs an explicit adapter before representing USDC base units,
USD payouts or claims; network identifiers cannot be relabeled across Arc/Base.

## What works together today

The repository combines a portable local Recovery Lab, the v0.3 protected
Purchase Simulator, the recorded Recovery Desk, the research evidence
adjudicator and the live decision experiments. All components are checked in
the same CI workflow. Each application owns its state and demonstrates a
different boundary; none is a production adapter around another component.

| Component | Entry point | State and boundary |
|---|---|---|
| Research runtime | `worker.py`, `belay/runtimes/anchored.py` | Research journal, permission store and synthetic services; POSIX crash experiments |
| Evidence adjudicator | `second/adjudicate.py`, `second/apply.py` | Research dossiers and evidence; may complete a verified absent effect through a callback |
| Recovery Desk | `experiments/recovery_demo.py`, `viewer/build_viewer.py` | Recorded POSIX crash scenarios using the research runtime and adjudicator; browser controls only inspect recordings |
| Optional recovery model | `second/live_agent.py` | OpenAI proposes evidence pointers and claims; deterministic validation and the guarded executor retain control |
| Live decision experiment | `experiments/run_live_agent.py` | Optional API-backed measurement and committed results; not the lab's decision engine |
| Recovery Lab | `python -m prototype.server` | Separate SQLite application/provider stores and loopback HTTP; scripted decisions and fictional money |
| Protected Purchase Simulator v0.3 | `python -m purchase_simulator.server` | Separate SQLite application and provider records; bounded ticket grant, deterministic policy, fictional USDC-to-USD settlement, USD merchant payout, delivery evidence, reserve accounting, claims and exact-operation recovery |
| Live autonomous USDC app and guarantee | Architecture and proposal documents | Future contracts, custody/provider integrations and funded terms; no deployed blockchain, live purchases, subscriptions, active coverage or real reimbursements |

Keep lab data under `.belay-prototype/` or another isolated directory. Do not
point it at research evidence or treat its database as the JSONL research
journal. Preserve committed `results/` when validating documentation; they
are research evidence rather than application state.

The Purchase Simulator uses `.belay-purchase-simulator/` and port 8777, with
no imports from the research or Recovery Lab execution engines. Its
`belay.purchase.v0.3` state keeps customer USDC, an order hold, provider transit,
merchant USD, protection cash, coverage commitments and claim payments
separate. The deterministic policy and fictional provider are also separate
modules, while admission, ledger and claim transitions share one local SQLite
transaction boundary. Stable identities prevent a lost provider reply from
creating a second payout.

Only browser-to-loopback requests are actual HTTP. Internal service calls use
invented `belay://` or `.invalid` traces. No token is transferred, no currency
is converted and no bank or reserve is connected. The records are deliberately
simplified and are neither AP2 messages nor deployed blockchain contracts. See
[PURCHASE_SIMULATOR.md](PURCHASE_SIMULATOR.md) for scenarios and limitations.

## Run and test

From a clone with Python 3.10 or newer:

```bash
python -m prototype.server --port 8765
python -m unittest discover -s tests -p "test_prototype.py" -v
python -m purchase_simulator.server --port 8777
python -m unittest discover -s tests -p "test_purchase_simulator.py" -v
node --check purchase_simulator/web/app.js
python tests/test_evidence_boundaries.py
python tests/test_live_agent.py
python tests/test_evaluate_recovery.py
python experiments/check_docs.py
```

Both application servers bind to `127.0.0.1`; they are local development
demonstrations. Use one server per application data directory. No external
payment credentials are needed. The applications run from a clone; the
existing distribution described by `pyproject.toml` does not package either
web application or its assets.

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

[INTERNAL_PAYMENT_PROTOCOL.md](INTERNAL_PAYMENT_PROTOCOL.md) develops this
boundary into proposed USDC API/adapter contracts. The
[settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md) defines on-chain
grants, temporary order holds, protected dispatch, withdrawals, a separate
protection reserve and external fiat conversion/payout records.
The current v0.3 default is USD supplier prepayment through an approved partner;
eligible post-payment reimbursements use a separate protection reserve. Supplier
crypto wallets/signatures are not required by the main flow. See the complete
[MVP master plan](MVP_MASTER_PLAN.md) before adapting the older demo traces.
The Purchase Simulator now implements local state-machine equivalents for that
flow, including a 1:1 zero-fee conversion fixture and seeded reserve. It does
not implement the proposed `/internal/v1` services, a chain transaction,
provider compliance, bank settlement or legally funded coverage.

The production app should expose one controlled action submission boundary. The
planner supplies a proposal; the authority service validates it and the
executor records and performs the permitted operation. This is an extension
contract, not a claim that the simulator's in-process Python boundaries provide
production isolation.

The record passed across that boundary must retain:

- User, mission and stable operation identity, kept separate from a provider's
  request/receipt identifiers.
- Grant version, allowed action, provider and credential reference.
- Exact immutable intent, quote/version/hash, amount and currency.
- Reserved budget, submission status and verified provider evidence.
- Chain, token and contract identity, grant/order slot, signer/nonce,
  replacement transaction lineage, block hash and observed finality.
- Pinned delivery/dispute policy, fixed beneficiaries, allocation/withdrawal
  states and independent conversion-provider/payout records.
- Net USD supplier amount, verified bank beneficiary reference, source USDC
  cap/fees, reserve exposure, coverage version, claim and recovery identities.

An adapter declares its actual capabilities and retry rules. A success response
needs evidence tied to the original operation and exact inputs. A failed
connection or empty lookup does not automatically establish absence. Provider
idempotency scope and lifetime must be respected across restarts.
For chain adapters, contract-enforced operation uniqueness and canonical-state
reconciliation complement the local journal. RPC receipt arrival is not
finality; removed events must be unwound from the derived view after a reorg.

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

The purchasing model cannot approve its own reimbursement. The v0.3 simulator
shows this separation with distinct case, economic-loss and payout identities,
an independent claim transition and a seeded fictional reserve. It deduplicates
the local payment for one loss, but it does not supply subscription entitlement,
financial-loss assessment, insurance authority or real claim funding. The
current research adjudicator supplies none of those production authorities
either.

## Migration gates

Before calling a future integration ready, demonstrate policy rejection,
concurrent budget reservation, expired/revoked authority, provider challenges,
crash recovery, delayed evidence and duplicate callbacks with the chosen
provider. Preserve unknown outcomes when evidence is insufficient. Verify
the exact adapter and payment/mandate profile; do not infer compatibility
from similar names or fields.

The USDC extension additionally requires grant conservation, signature replay
protection, expiry/revocation ordering, release/refund exclusivity, failed-token
withdrawals, resolver timeouts, gas failure and reorg tests. The research
adjudicator is not a production delivery verifier or an authorized arbitrator.
It also requires conservation across held/dispatched funds and reserve claims,
late bank returns, protection expiry and no duplicate remedy for the same loss.

Known original-runtime defects remain documented in [REVIEW.md](REVIEW.md).
Neither the separate lab suite nor an architectural diagram proves that
the research runtime or a future live app is production-ready.
