# PR #10 review: recovery component and payment architecture fit

Reviewed September 13, 2026: [Add AI Apps Recovery Desk and MetaMask testnet recovery](https://github.com/Frank-7/Belay/pull/10).
Head: `1b056c096b0bab1844a93bd18a77186dfec0ec93`.
Current main/base: `cffe7ac229cd0d2883b5ac336420b126d291990d`.

## Recommendation

Reuse this as Belay's payment-outcome investigation component. Address the
confirmed-failure dead end below before calling the test-wallet lifecycle
complete. The PR is a draft; its description correctly leaves a real user-signed
testnet demonstration outstanding. Its `ci` and `pages` workflow runs report
success for the reviewed head.

Main is an ancestor of this head. `git merge-tree --write-tree origin/main HEAD`
succeeds without conflicts. This establishes Git compatibility with current
main, not production financial safety. No merge, teammate-branch modification,
transaction, paid model request or GitHub review/comment was made in this review.

## Actionable finding

**P2 — Close verified reverted transfers without authorizing a retry.**

In [engine.py line 499](https://github.com/Frank-7/Belay/blob/1b056c096b0bab1844a93bd18a77186dfec0ec93/recovery_app/engine.py#L499),
`_refresh_arc` creates usable evidence only for `committed`. The Arc verifier
already recognizes an exact, canonical-finalized receipt with `status: 0` as
`failed`. That becomes empty lossy evidence, so investigation returns
`needs_evidence`/`abstain` and resolution rejects it. `prepare_wallet` lines
433–436 then rejects every newly authorized identical sender/recipient/amount
because the old incident remains unresolved. The browser likewise permits a
form reset only for `resolved` (`wallet.js` lines 95–103).

Reproduced offline with the actual `ArcEvidenceProvider` and the existing
receipt fixture changed to status zero and no transfer logs. After prepare,
dispatch, hash attachment and investigation:

```text
Verified provider outcome: failed
Application outcome: needs_evidence abstain
Resolve refused: 409 Evidence does not support a resolution
New explicit same-tuple transfer refused: 409 An identical test transfer is still unresolved.
```

Add a journaled, evidence-bound terminal failure that preserves the original
hash and gas disclosure and sends no money. Permit a separate, explicitly
authorized incident afterward. Missing/pending receipts and ambiguous wallet
errors must remain unknown; they do not authorize retries. Regression coverage
should include restart, duplicate closure and stale evidence. This is a
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

## Combining with the simulator branch

Merge-tree preview against `codex/purchase-simulator` at `5fa1382`
reports seven conflicts: `.github/workflows/ci.yml`, `.gitignore`, `Makefile`,
`README.md`, `docs/INDEX.md`, `docs/INTEGRATION.md`, `docs/NEXT_STAGE.md`.
The v0.3 architecture documents are included in that preview and need
preservation during integration.

Keep both test targets, data-directory exclusions and application entry points.
Preserve main's fixes and historical research numbers. Describe Recovery Desk
as implemented recovery, Purchase Simulator as fictional shopping and v0.3 as
the product specification. Merge shared documents by meaning; choosing one
whole side would discard content. A combined product merge has not been done.

## Checks performed here

- Python: 16 Arc verifier and 17 Recovery Desk tests passed.
- Evidence boundaries: 19 ran, 17 passed and two Windows symlink tests skipped.
- Three holdout and three export tests passed.
- Node: 30 wallet and Recovery Desk frontend tests passed.
- Reproduced the finalized-revert dead end with an offline RPC fixture.
- GitHub CI and Pages succeeded for this head. Full POSIX crash tests were not
  rerun locally on Windows; no actual wallet transfer or model call was made.

These results support a bounded recovery prototype. They do not establish
mainnet safety, provider approval, model superiority or funded coverage.
