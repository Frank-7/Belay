# Next stage

## Deliverable now

The repository contains the local Recovery Lab, Purchase Simulator and the
selected [USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md).
The [MVP master plan](MVP_MASTER_PLAN.md) and [presentation script](MVP_PRESENTATION.md)
now specify the complete agent, USD merchant payment and funded-protection flow.
The contract, chain adapters and fiat conversions are proposed; these documents
do not activate coverage, subscription billing or a payment integration.
Use [the index](INDEX.md) to distinguish implemented work from plans.

## First build increment

Extend the two-panel purchase demonstration with the USDC contract workflow:
owner funding, bounded mission grant, exact order, conversion quote, USD supplier
payout, receipt/evidence, separate claim decision and reserve reimbursement.
Keep concert tickets as the example and use fictional assets/providers first.

Done means: a two-ticket $200 order debits the quoted USDC from a $300-limit mission once; duplicate/replayed
requests cannot debit it again; wrong items/merchant and excessive costs are
blocked; still-held funds can be returned; eligible loss after USD payout is
paid from separately visible protection capital; contested evidence goes to
review; restart preserves unknown operations. Show USD
conversion and bank payout separately from token settlement. Label the current
simulator's earlier provider flow accurately until this extension is built.

## Second build increment

Build the proposed Solidity contract and local EVM invariant tests, then
integrate a Base testnet wallet, protected signer, relayer/RPC and canonical
event indexer. Test signatures/nonces, conservation, deadline races, revoked
grants, token-transfer failure, missing receipts, transaction replacement and
reorganization recovery. Mock ticket delivery and conversion providers until
their actual integrations are approved. No real funds in these increments.

Next, establish one merchant's accepted USD payment method and an approved
buyer-funded conversion/payout route. The seller needs no crypto account. Live use
requires reviewed contract code, accepted release/dispute terms, delivery
evidence access and approved operating responsibilities. The full gates are
in [the settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md).

A separate agent-error case is part of the presentation. It must distinguish returning
still-held purchase funds from paying additional compensation and deduct prior recoveries. An
unknown purchase is not automatically a loss; actual claims remain unavailable
until payer, funding and terms are established.

Reuse the teammate's draft [PR #10](https://github.com/Frank-7/Belay/pull/10)
as the payment-outcome investigation slice after addressing the finalized-revert
dead end documented in [the payment review](PR10_PAYMENT_REVIEW.md). Adapt it
through typed provider observations; do not turn its read-only recovery model
into the autonomous spender. Preserve both application test suites when merging.

## Commercial validation in parallel

| Work | Evidence required before advancing |
|---|---|
| Interview frequent delegators | A recent failed purchase/task, real impact and current workaround |
| Test the offer | Willingness to delegate and pay at a clearly disclosed cap; compare service-only and guarantee propositions |
| Confirm financial structure | Named payer, reviewed terms, funded obligations and approved launch scope |
| Confirm provider access | Accepted USD order/payment method; authorized customer-to-supplier conversion/payout route; delivery and recovery evidence |
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

- Use native USDC on Base, bounded grants, approved USD supplier payout and
  separately funded protection for eligible post-payment losses.
  Stripe/card payment selection is superseded; no blockchain deployment exists yet.
- Demonstrate a separately funded reserve; evaluate an authorized partner for
  agreed live risk bearing/replenishment. No reserve, partner or policy is live.
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
