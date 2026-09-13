# Next stage

## Deliverable now

The repository contains the local Recovery Lab, Purchase Simulator and the
selected [USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md).
The contract, chain adapters and fiat conversions are proposed; these documents
do not activate coverage, subscription billing or a payment integration.
Use [the index](INDEX.md) to distinguish implemented work from plans.

## First build increment

Extend the two-panel purchase demonstration with the USDC contract workflow:
owner funding, bounded mission grant, merchant-signed quote, order escrow,
delivery attestation, challenge/dispute, allocation and withdrawal. Keep concert
tickets as the example and use fictional assets/providers first.

Done means: a 42 USDC order debits a 100 USDC grant once; duplicate/replayed
requests cannot debit it again; wrong items/merchant and excessive costs are
blocked; no delivery refunds remaining escrow; contested delivery uses the
pinned resolver and timeout; restart preserves unknown operations. Show USD
conversion and bank payout separately from token settlement. Label the current
simulator's earlier provider flow accurately until this extension is built.

## Second build increment

Build the proposed Solidity contract and local EVM invariant tests, then
integrate a Base testnet wallet, protected signer, relayer/RPC and canonical
event indexer. Test signatures/nonces, conservation, deadline races, revoked
grants, token-transfer failure, missing receipts, transaction replacement and
reorganization recovery. Mock ticket delivery and conversion providers until
their actual integrations are approved. No real funds in these increments.

Next, establish one merchant and the buyer/seller conversion routes. Live use
requires reviewed contract code, accepted release/dispute terms, delivery
evidence access and approved operating responsibilities. The full gates are
in [the settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md).

A separate guarantee simulation can follow. It must distinguish returning
escrow from paying additional compensation and deduct prior recoveries. An
unknown purchase is not automatically a loss; actual claims remain unavailable
until payer, funding and terms are established.

## Commercial validation in parallel

| Work | Evidence required before advancing |
|---|---|
| Interview frequent delegators | A recent failed purchase/task, real impact and current workaround |
| Test the offer | Willingness to delegate and pay at a clearly disclosed cap; compare service-only and guarantee propositions |
| Confirm financial structure | Named payer, reviewed terms, funded obligations and approved launch scope |
| Confirm provider access | Merchant accepts USDC/escrow terms; delivery source, conversion routes and recovery behavior are verified |
| Observe a controlled pilot | Eligible actions, net losses, unresolved outcomes, support cost and repeat use |

Do not invent demand or broad market statistics from interviews that have not
happened. A small pilot can expose problems without proving a rare-loss rate.
Before expanding limits, test common-cause failures and delayed claims as
well as ordinary successful purchases.

## Expansion after the first working mission

Add one paid research mission using the same grants, budget ledger, executor
and evidence model. Use named sources for trends and traffic estimates.
Do not build an agent marketplace or support every merchant at once.

For the hackathon, target a complete demonstration by hour 48. The supplied
72-hour playbook conflicts with the stated 48-hour environment window.
If 72 hours is confirmed, use the remaining time for hardening and evaluation.
Prepare a repository link and 60-second progress video for each required
check-in; confirm the actual schedule with the organizers.

## Selected direction and remaining dependencies

- Use native USDC on Base, prefunded grants and contract release/refund rules.
  Stripe/card payment selection is superseded; no blockchain deployment exists yet.
- Belay supplies the app and its service-fee remedy. Pursue a licensed partner
  for transaction-loss protection; no partner or policy is secured.
- Exact guarantee triggers, amount limits, price and initial live jurisdiction.
- Which merchant, delivery verifier, dispute operator and conversion providers
  accept the selected arrangement; exact US operating/control responsibilities.

The architecture and simulator can proceed while these decisions are resolved.
Live financial promises depend on the payer, terms and permissions actually
being ready.

## Recent repository work to preserve

The main branch now includes a separate Gemini decision-stability experiment
and an evidence adjudicator under `second/`. The Gemini results preserve
separate archived and partial runs, including the earlier 150-response sample.
Inspect each run's configuration and completion counts before quoting its
results. These measurements do not establish a production error rate or
replace the proposed app planner.
The adjudicator evaluates evidence for research recovery; it is not a claims
operation or a funded reimbursement service. Preserve these additions when
integrating the Recovery Lab and current product documents.
