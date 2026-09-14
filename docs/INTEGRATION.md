# Repository integration guide

The primary AI Apps product is **Belay Recovery Desk**: an operator investigates
what an interrupted agent action did and records a supported outcome. The
**Purchase Simulator** makes the same problem tangible for a customer funding
USDC while a merchant accepts USD. Its uncertain payouts now use Recovery
Desk's typed, read-only evidence component inside the purchase service.

## Components and boundaries

| Component | Entry point | Actual behavior |
|---|---|---|
| Local Recovery Desk | `python -m recovery_app.server --port 8766` | Persistent incidents, research JSONL journal, bounded `second/` evidence validation, refresh, guarded resolution and receipts. |
| Optional recovery model | `second/live_agent.py` | Configured OpenAI model proposes evidence pointers and a cited verdict; deterministic validation and operator/executor control remain separate. |
| Local refund provider | `services/ledger.py` through `recovery_app/engine.py` | Real local SQLite writes with fictional amounts and constructed interruptions; creating an incident is not an OS-crash trial. |
| Arc Testnet adapter | `recovery_app/arc.py`, browser wallet module | A person signs capped test-USDC transfers in MetaMask; the server reads and verifies the original transaction. |
| Purchase Simulator | `python -m purchase_simulator.server --port 8777` | Fictional grants, USDC funding, USD payouts, delivery, claims and reserve accounting in separate application/provider SQLite stores. |
| Purchase recovery bridge | `purchase_simulator/recovery.py` → `recovery_app/purchase.py` | Typed deterministic investigation of the saved purchase and original provider observation; no ledger, signer or payout callback enters the evidence core. |
| Research runtime | `worker.py`, `belay/runtimes/anchored.py` | Journal, permission store, synthetic external services and POSIX SIGKILL experiments. |
| Research evidence adjudicator | `second/adjudicate.py`, `second/apply.py` | Research dossiers and guarded completion of verified absent local refund effects; this completion callback is not a purchase payment interface. |
| Recorded demonstrations | `recovery_app/export.py`, `experiments/recovery_demo.py`, `viewer/build_viewer.py` | Static operator scenarios and recorded real-crash research traces; browser controls only inspect saved results. |
| GitHub Pages | `site/`, `scripts/build_site.py` | Product introduction and recordings; no Python API or model credentials. |
| Legacy Recovery Lab | `python -m prototype.server --port 8765` | Earlier separate SQLite implementation for baseline comparison. |
| Future protected commerce | Architecture/proposal documents | Base contracts, approved conversion/payout providers, merchant integrations and funded protection; none is a live service. |

The integrated implementation fixes the review's two defects: finalized Arc
reverts can close as failed without sending, and purchase dispatch uncertainty
survives a provider/app commit gap. Auto play stops at uncertainty while explicit
investigation and reconciliation remain available. The original seven shared
conflicts concerned CI, `.gitignore`, Makefile, README and the index/integration/
next-stage documents. Both applications, test targets, state exclusions and
research results are retained. [The historical review](PR10_PAYMENT_REVIEW.md)
keeps the original reproduction and reviewed revision for context.

## Run locally

From a clone with Python 3.10 or newer, start each server in its own terminal:

```bash
python -m recovery_app.server --port 8766
python -m purchase_simulator.server --port 8777
```

Open `http://127.0.0.1:8766` for Recovery Desk or
`http://127.0.0.1:8777` for the purchase use case. On Windows,
double-click `Start-Belay-Simulator.cmd` to launch the latter; leave its
terminal open. Its isolated data directory is
`.belay-purchase-simulator/demo-v4/`.

Default state directories are `.belay-recovery/`,
`.belay-purchase-simulator/` and `.belay-prototype/`. Use `--data-dir` for an
isolated run and one server per application data directory. The Recovery Desk
has a process ownership lock; the purchase app serializes writes through SQLite
and its engine lock. Neither loopback development server is an authenticated
hosted service. Run from a clone: the existing distribution does not package
these web applications and assets.

The deterministic demos need no credentials. To enable the optional Recovery
Desk model, set `OPENAI_API_KEY` and an explicit `OPENAI_MODEL` in the server
environment. Each investigation permits at most two model requests and no
automatic retries. Requests may incur charges. The model receives bounded
evidence, never signing material, payment credentials or an execution callback.
The purchase investigator is deterministic and makes no model request.

```bash
python -m unittest discover -s tests -p "test_recovery_app.py"
python -m unittest discover -s tests -p "test_arc.py"
python -m unittest discover -s tests -p "test_purchase*.py"
node --test tests/test_purchase_simulator_ui.mjs
python tests/test_evidence_boundaries.py
python tests/test_live_agent.py
python tests/test_evaluate_recovery.py
python tests/test_recovery_holdout.py
python experiments/check_docs.py
python experiments/evaluate_recovery.py --audit-unvalidated --out tmp-runs/recovery-evaluation.json
python experiments/recovery_holdout.py --out tmp-runs/recovery-holdout.json
```

The raw-claim audit is classification only and never executes an unvalidated
dossier. Optional model comparison uses
`python experiments/evaluate_recovery.py --agent openai --model MODEL_ID`.
Both agents receive identical isolated cases and evidence limits; this is not
an equal-compute comparison. Full contract and recorded crash tests need Linux,
macOS or WSL for POSIX signals. Preserve committed `results/`: they are
historical research evidence, not app state. CI checks committed documentation
before generating, validating and uploading fresh experiment artifacts.

## Evidence and authority

The research evidence store restricts files to its root. A model requests at
most 16 pointers. Deterministic context checks cover at most eight advertised
sources, a manifest and exact-order query for each. Each source has a 1 MiB and
1,000-record limit. Unreadable or over-budget evidence yields abstention.
Cited observations must actually have been fetched. Context can veto an omitted
contradiction but cannot supply missing support on a model's behalf. Local file
provenance and claimed coverage are assumptions, not authenticated merchant
attestations or consensus.

Applying a research dossier requires the original intent, current halted
journal and unchanged evidence. Reporting a proven commitment sends nothing.
Completing a verified absent local refund rechecks permission immediately before
the simulated call. That research completion path is not exposed to purchases.

## How purchase recovery uses the core

The bridge retains the original mission/run, order, operation, grant digest,
beneficiary, exact intent and separate currency fields. USDC amounts are integer
six-decimal base units; USD amounts are integer cents. It does not put USD
payouts, claims or arbitrary token units into the research `amount_cents` refund
slot. No fictional chain identifier or Arc/Base conversion is invented.

`Engine.investigate` checks the requested revision and reads the original
provider operation. The typed core checks that observation and returns a
`paid`, `unknown` or `conflict` finding with evidence digests and reasons.
It cannot convert funds, complete a payout, change a ledger or approve a claim.
Reconciliation runs in the purchase executor, checks the source revision,
operation and intent, rereads the provider, requires an unchanged evidence
digest and validates the exact settlement before accounting for it once.

Before the first provider submission, the application commits an immutable
dispatch record and an unknown state while retaining the customer's order hold.
Acceptance accounting is a second durable transition. After a crash, recovery
reads the same operation before quote/grant expiry, changed terms or cancellation
can release the hold. A matching received operation moves the hold to provider
transit once; a matching paid operation can reconcile the existing USD payout.
An empty, unreadable or conflicting record leaves funds reserved and never
authorizes a resubmission. Older unjournaled provider operations block release
and require manual review. A changed permission still blocks a genuinely new
dispatch; it cannot recall a provider's already accepted operation.

The purchase simulator's provider, rate `1 USDC = $1.00`, zero fees, signatures,
tickets and reserve are fixtures. Its `.invalid` traces describe conceptual
service calls, not external network integrations. Customer funds, merchant USD,
reserve cash, coverage commitments, claims and economic-loss identities stay
separate. A reserve remedy is an additional fictional payment; it does not
reverse USD already paid to the merchant. See [PURCHASE_SIMULATOR.md](PURCHASE_SIMULATOR.md).

## Test-wallet demonstration

The implemented wallet path is Arc Testnet, chain ID `5042002`, and Circle's
test-USDC token, with amounts 0.01–1.00 in 0.01 increments. MetaMask holds the
person's key; Belay stores public intent and transaction evidence. A faucet
balance, network access and the person's signature are external dependencies.
Neither server nor model signs or sends a replacement transfer. See
[TEST_WALLET.md](TEST_WALLET.md).

Successful receipt recovery verifies chain, token, sender, recipient, amount,
transaction identity, Transfer event and canonical finalized block. A verified
finalized revert can close as failed, preserving its hash and test-gas
disclosure; it sends nothing and is not evidence of an absent request. Starting
another transfer requires a new intent and explicit signature. Missing,
unfinalized or inconsistent evidence keeps the original incident unresolved.
The RPC and network remain trust assumptions; this is not a light-client proof.

The proposed Base route has different chain/token/finality/provider requirements.
Changing a label cannot migrate Arc evidence to Base or create a USD payout.
The current transfer tuple and supplied original hash are not cryptographic
per-order attribution. Production designs must establish stronger operation
correlation and replacement-transaction lineage as appropriate to the provider.

## Future provider and protection boundaries

[MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md),
[USDC_SETTLEMENT_ARCHITECTURE.md](USDC_SETTLEMENT_ARCHITECTURE.md) and
[INTERNAL_PAYMENT_PROTOCOL.md](INTERNAL_PAYMENT_PROTOCOL.md) preserve the future
commerce proposal: approved customer-USDC conversion, USD merchant settlement,
bounded execution and separate funded remedies. No provider account or sandbox
credentials are configured, so a real provider integration remains deferred.

Before live use, establish an accepted merchant order/payment method, approved
conversion route, beneficiary controls, authenticated evidence and explicit
idempotency/finality semantics. Test revocation, deadlines, concurrent budgets,
crash gaps, duplicate callbacks, delayed evidence and transaction replacement.
Future chain contracts require their own reviewed invariants and deployment
process; this simulator supplies no contract-level enforcement.

Purchase recovery and customer compensation require separate authorizations.
A claims service must assess eligible unrecovered loss against actual terms,
prior recoveries and funded capacity; the purchasing model cannot approve its
own reimbursement. The local reserve fixture supplies no subscription
entitlement, insurance authority or real funding. A local audit receipt is
evidence of the application's decision, not a financial guarantee.
