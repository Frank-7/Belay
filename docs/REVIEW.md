# Belay engineering review — updated 13 September 2026

Belay's current product is an operator application for recovering uncertain
agent actions. The local Recovery Desk now uses the research JSONL journal,
`second/` evidence validator and guarded application path. Its local refund
provider is simulated. The separate Arc Testnet path reads evidence for a
transfer that a person signs in their browser wallet.

The original review examined commit `7c68e95`. Its two high-priority defects
were fixed in PR #7, merged at `cffe7ac229cd0d2883b5ac336420b126d291990d`.
Earlier versions of this document incorrectly continued to list them as open.

## Findings and status

| Status | Finding | Evidence or remaining work |
|---|---|---|
| **Fixed in PR #7** | Appending after a torn journal tail could hide later durable records | Journal append repairs an incomplete tail, rejects interior corruption and handles short writes; runtime recovery regressions cover these cases. |
| **Fixed in PR #7** | An interrupted anchor allocation could leave only one required slot | Initialization completes valid partial allocation and rejects inconsistent persisted state. |
| **Fixed in this application increment** | The model could select supporting evidence while omitting a contradictory source | Adjudication scans at most eight available sources for consistency. Conflicts, unreadable sources and budget exhaustion abstain. Context can veto a claim but cannot supply a missing model citation. |
| **Fixed in this application increment** | Malformed amounts, source identity or coverage could raise or be misread | The store and validator reject malformed snapshots; exact order, amount and source identity remain bound to the request. |
| **Open** | Research fsync counts omit killed-worker work when no outcome file was written | Do not present the historical approximately 12% figure as total workflow overhead. |
| **Open** | The historical grader does not cover every credit-slot outcome | Zero observed violations does not mean every two-slot property was tested. |
| **Open** | Research replay reconstructs some parameters from the current `PLANS` label | A deployment migration needs immutable persisted parameters and a versioned schema. |
| **Integration limit** | Empty remote lookup is not generic proof of absence | A provider needs a documented finality/completeness contract. Arc missing or nonfinal receipts remain unknown; the app never issues an Arc replacement transfer. |
| **Integration limit** | Local permission checking is not atomic with a remote commit | A wallet signature or already submitted transaction cannot be undone by later local revocation. |
| **Integration limit** | The application serializes one owner of a local data directory | This is not a distributed lease or support for concurrent remote recovery workers. |

The original high-priority reproductions were constructed persisted states,
not SIGKILL measurements. Their historical existence should not be cited as
an unresolved defect after PR #7.

## What the evidence supports

The committed crash experiment reports 960 confirmed SIGKILLs across four
runtimes, including zero observed violations in 240 anchored trials under
the stated contract. The committed evidence experiment reports 90 resolved
and 110 abstained cases, with zero false resolutions in 200 validated cases.
These are separate controlled experiments, not customer loss rates.

The new 24-case portable evaluation preserves the deterministic baseline:
8 resolved, 14 abstained, 2 permission refusals and zero false resolutions.
It separately reports resolution precision, useful resolution coverage,
unknown handling, latency, requests, tokens and optional caller-priced cost.
The 12-case constructed boundary suite yields 2 committed, 2 absent and
8 abstained classifications. Its cases are frozen after authoring; repeated
runs are regression evidence, not fresh holdout incidents.

No new live-model advantage or customer demand is claimed. The existing
Gemini samples found no within-cell decision disagreement in the completed
50-response cells. Inspect each configuration in
[`results/live_divergence.json`](../results/live_divergence.json); do not
pool separate conditions into a production rate.

## Comparison discipline

Correct stable-key retries and durable workflow systems are strong existing
baselines. Temporal can record nondeterministic Activity results, and an
Activity can check current business conditions before acting. Belay should
demonstrate a useful recovery workflow and explicit evidence boundaries
rather than claim those checks are impossible in Temporal.
[Temporal Activities](https://docs.temporal.io/activities)

Stripe idempotency protects retries with the same valid key and parameters;
keys may be pruned after at least 24 hours. This does not make an arbitrary
new-key retry safe or turn every empty lookup into final absence.
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)

The app does not hold money, operate escrow, reimburse losses or guarantee
transactions. A test token proves a test-network integration, not a funded
business or a production financial control. See [the integration guide](INTEGRATION.md)
for the implemented boundaries and [the execution plan](NEXT_STAGE.md)
for the next evidence needed.