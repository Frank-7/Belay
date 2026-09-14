# PR #10 integration record: Recovery Desk and payment architecture

Initially reviewed September 13, 2026:
[Add AI Apps Recovery Desk and MetaMask testnet recovery](https://github.com/Frank-7/Belay/pull/10).
The PR merged to main at `184dc9eda32d13dd399b613f398212cdb6f6f18d`.
Its finalized-failure lifecycle fix is `250456f`.

## Recommendation

Recovery Desk is now Belay's implemented payment-outcome investigation
component. Keep its read-only chain recovery separate from Payment Mission's
authority and executor. The pre-merge finding below was fixed before merge; it
is retained as an engineering record rather than an open blocker.

## Resolved finding

**P2 — Close verified reverted transfers without authorizing a retry. Resolved
in `250456f`.**

In [engine.py line 499](https://github.com/Frank-7/Belay/blob/1b056c096b0bab1844a93bd18a77186dfec0ec93/recovery_app/engine.py#L499),
`_refresh_arc` creates usable evidence only for `committed`. The Arc verifier
already recognizes an exact, canonical-finalized receipt with `status: 0` as
`failed`. That becomes empty lossy evidence, so investigation returns
`needs_evidence`/`abstain` and resolution rejects it. `prepare_wallet` lines
433–436 then rejects every newly authorized identical sender/recipient/amount
because the old incident remains unresolved. The browser likewise permits a
form reset only for `resolved` (`wallet.js` lines 95–103).

Before the fix, this was reproduced offline with the actual
`ArcEvidenceProvider` and the existing
receipt fixture changed to status zero and no transfer logs. After prepare,
dispatch, hash attachment and investigation:

```text
Verified provider outcome: failed
Application outcome: needs_evidence abstain
Resolve refused: 409 Evidence does not support a resolution
New explicit same-tuple transfer refused: 409 An identical test transfer is still unresolved.
```

The merged fix adds a journaled, evidence-bound terminal failure that preserves
the original hash and gas disclosure, sends no money and permits a separately
authorized incident afterward. Missing/pending receipts and ambiguous wallet
errors remain unknown; they do not authorize retries. Regression coverage
includes restart, duplicate closure and stale evidence. This was a
lifecycle/availability defect, not an observed double payment.

## Reusable components

| Component | Useful behavior | Product role |
|---|---|---|
| Incident and journal | Saves exact intent and dispatch before wallet request; reconstructs hash after interruption | Execution/reconciliation core |
| Wallet boundary | MetaMask holds keys and asks the person to sign; browser validates fixed transaction fields | User-signed testnet demonstration |
| Chain verifier | Exact transaction, successful token event and canonical finalized block; no retry on missing evidence | Read-only provider adapter |
| Evidence adjudicator | Bounded contradiction scan, current journal binding and stale-proposal rejection | Recovery assistant plus deterministic validator |
| Operator app | Persistent cases, evidence refresh and exported records | Initial recovery/support interface |

The optional LLM proposes evidence interpretations. It is not signer, executor
or claims payer. Keep that separation in the larger architecture.

## Post-merge legacy purchase integration

Commit `fe23651` adds a separate typed bridge for the ticket simulator's
`belay.purchase.v0.3` payout-reply-lost path. It persists a dispatch-attempt
record before provider I/O and keeps the exact order hold reserved when
acceptance may be unknown. A read-only investigator binds the run, mission,
order and operation IDs, grant digest, beneficiary, USDC base units, USD cents
and canonical intent.

The investigator returns `paid`, `unknown` or `conflict`; only exact paid
evidence sets `can_reconcile`. Missing, unavailable, partial or contradictory
evidence cannot release funds or authorize another submission. Reconciliation
re-reads the provider and accounts the original payout once only if the
evidence is still identical. The API accepts only the current revision at
`POST /api/runs/{id}/investigate` and does not accept a client verdict.

This is an implemented legacy compatibility path. It is not wired into the
generalized `belay.mission.v0.1` investor flow, and it does not turn Recovery
Desk into a signer, ledger, provider client, claims service or autonomous
executor.

## Missing product layers

| Intended capability | PR boundary | Build next |
|---|---|---|
| Autonomous purchase under prior approval | Person signs each test transfer | Scoped grant and protected executor |
| USDC buyer, USD seller | Wallet-to-wallet test USDC | Approved conversion/payout adapter and accepted merchant invoice/order |
| Hold funds until agreed delivery | No escrow contract | Optional reviewed hold/release module |
| Verify usable tickets or damaged goods | Checks token movement only | Delivery evidence and dispute rules |
| Return money after seller payment | Records the original transfer; cannot reverse it | Actual supplier recovery or separately funded reimbursement |
| Agent-error guarantee | No cover or reserve | Independent claims authorizer and funded protection ledger |
| Cryptographic order identity | ERC-20 transfer has no Belay order ID | Signed order/grant binding and contract/provider correlation |

## Chain and data compatibility

Keep the working Arc Testnet adapter explicitly named. The v0.3 contract plan
targets native USDC on Base. Chain IDs, token addresses, gas and finality rules
cannot be swapped by changing a label. No bridge or automatic migration is
implied. Confirm payout-provider chain support before choosing a live route.

Arc's six-decimal ERC-20 demo restricts amounts to cent increments, permitting
projection into the research `amount_cents` refund slot. That must not become
the general payment schema. Store asset, chain ID, token address, decimals and
integer base units for USDC; use a distinct integer USD minor-unit field for
payouts. Arc's native and ERC-20 interfaces represent the same underlying
balance and must not be added together.

Keep chain recovery read-only. Add a separate executor and typed adapters;
do not give the recovery model a send tool. Version the original refund-only
schemas before using them for purchases, bank payouts or claims. Preserve the
documented assumption that an operator attaches the original hash: another
same-tuple external transfer is not cryptographically bound to the order.

## Combining with Payment Mission

Keep both test targets, data-directory exclusions and application entry points.
Recovery Desk uses port 8766 and `.belay-recovery/`; Payment Mission uses port
8777 and `.belay-purchase-simulator/`. Preserve main's fixes and historical
research numbers. Treat Recovery Desk as implemented recovery and Payment
Mission as a separate local payment simulation. The legacy v0.3 ticket path now
has a typed, read-only provider observation; connect the generalized v0.1
mission path later through its own adapter rather than a shared executor or
database.

## Checks performed here

- Python: 16 Arc verifier and 17 Recovery Desk tests passed.
- Evidence boundaries: 19 ran, 17 passed and two Windows symlink tests skipped.
- Three holdout and three export tests passed.
- Node: 30 wallet and Recovery Desk frontend tests passed.
- The original review reproduced the finalized-revert dead end; the merged
  regression suite covers the corrected terminal-failure behavior.
- The later legacy purchase bridge adds focused tests for provider/application
  commit gaps, expiry and cancellation hold safety, evidence conflicts,
  unavailable evidence, exact revisions and no replacement submission.
- GitHub CI and Pages succeeded for this head. Full POSIX crash tests were not
  rerun locally on Windows; no actual wallet transfer or model call was made.

These results support a bounded recovery prototype. They do not establish
mainnet safety, provider approval, model superiority or funded coverage.
