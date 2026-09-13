# Subscription and customer guarantee proposal

**Internal product proposal, not an active offer or a coverage contract.**
The payer, launch jurisdictions, terms, price and limits are not approved.
The examples below are design assumptions for review, not measured loss rates.

## The offer in simple words

The customer subscribes to an agent that executes permitted tasks, monitors
results and helps resolve problems. The customer pays for valid purchases.
A proposed guarantee would reimburse a limited amount of eligible financial
loss caused by Belay's own execution errors.

Potential customer wording, only after the actual terms and legal route are
established:

> Give Belay a goal and spending boundaries. It handles eligible tasks
> automatically and keeps a record of the results. If a verified Belay
> execution error causes a direct financial loss, the guarantee reimburses
> eligible unrecovered loss up to the published limits.

This does not mean free purchases, unlimited compensation or that every
merchant problem is covered. A refund of the Belay subscription fee is a
different remedy from reimbursement of a ticket or other transaction loss.
The interface must identify which remedy applies before the customer subscribes.

## Two viable stages for the offer

| Stage | Proposed customer remedy | What must exist |
|---|---|---|
| Initial service pilot | Support and recovery assistance; a defined refund of Belay's service fee for eligible service failure | Clear service terms, evidence, support ownership and review of the launch jurisdiction |
| Transaction guarantee pilot | Capped reimbursement for specified Belay-caused direct losses | Approved contractual route, named payer, funded obligations, claims process and observed loss data |

Recommendation: build the transaction-guarantee simulator now, while launching
live services only with the remedy actually ready to be honored. Do not sell
a transaction guarantee and silently substitute service credits.

**Selected route: stage the remedies.** Belay funds its own defined service-fee
remedy and handles execution support. Pursue an appropriately authorized
insurance partner for covered transaction losses before offering that benefit
live. Belay supplies evidence and customer support; the partner's agreed
contract determines claim decisions and who pays. For the target arrangement,
the partner pays covered transaction claims, while Belay pays its separate
service-fee remedy. No partner or policy is currently secured.

This avoids using subscription receipts as the sole funding source for
transaction losses. It does not eliminate Belay's legal, distribution or
operational responsibilities. See the
[recovery and guarantee decision](RECOVERY_AND_GUARANTEE_DECISION.md).

## A narrow transaction guarantee to evaluate

Start with duplicated or explicitly out-of-scope purchases caused by a
verified defect in Belay's execution service. Limit eligible activity to
named connectors and task types that produce useful independent evidence.

| Case | Proposed treatment | Why |
|---|---|---|
| Belay creates a second paid order for one authorized purchase | Eligible direct unrecovered loss, subject to terms and caps | An execution defect caused an extra charge |
| Belay purchases an event/date prohibited by the recorded grant | Review for eligible direct unrecovered loss | A verifiable requirement was violated |
| Belay pays once but loses the response | Reconcile first; not automatically a reimbursable loss | An unknown result is not itself financial damage |
| Merchant refund fully restores the additional charge | No duplicate reimbursement for the same loss | The loss has been recovered |
| Customer changes their mind after a correct purchase | Outside this proposed guarantee | Belay executed the authorized action |
| Event is cancelled or a seller fails to deliver despite a correct purchase | Merchant/provider remedies; outside the narrow execution guarantee | This adds third-party performance risk |
| Lost income, investment losses or missed opportunities | Outside this proposed guarantee | Indirect or speculative damage is a different exposure |

Exclusions from this proposed voluntary benefit do not remove applicable
customer rights or settle Belay's other legal obligations.

### Illustrative limits for a simulated offer

- USD 100 per eligible incident and USD 200 per subscriber per contract year.
- No separate deductible in this example; ordinary purchase costs remain payable.
- The entitlement and terms version are recorded when the action is accepted.
- Cancellation of a subscription does not erase obligations arising from an
  already eligible action. Terms must define claim timing and survival.
- New enrollment and future delegated exposure can be reduced prospectively;
  existing valid obligations cannot be cancelled because the budget is exhausted.

These caps are placeholders to stress-test the design. A USD 280 duplicate
ticket purchase could leave a customer with USD 180 unreimbursed under the
USD 100 incident cap. That limitation must be obvious; do not market this as
complete financial protection. A meaningful cap must be selected using the
chosen workflow, customer expectations and available funding.

## How a claim would work

1. Capture the incident, affected operation and entitlement without requiring
   the customer to reconstruct information Belay already has.
2. Preserve the original grant, exact submitted request, software/connector
   version, provider IDs, receipts and relevant activity records.
3. Reconcile the payment and order. Seek cancellation/refund where appropriate
   under the customer's authority. Track partial and pending recoveries.
4. Establish causation, actual direct loss, prior recoveries and applicable
   limits. Missing Belay logs alone must not automatically defeat a valid claim;
   accept other relevant evidence and provide an appeal path.
5. A designated reviewer decides initial pilot claims and gives a clear reason.
   Use a separate authorized payout operation, its own stable ID and receipt.
6. Record subsequent refunds or recoveries under disclosed terms so the same
   loss is not paid twice. Correct the underlying defect before expanding use.

Example calculation: an eligible error creates USD 100 of direct loss; the
merchant returns USD 60. The remaining eligible loss is USD 40, before any
other applicable cap. The valid intended purchase is not counted as a loss.

A draft operational target is acknowledgement within one business day and
a decision within seven business days after necessary evidence is available.
Keep the customer informed of unresolved provider responses. Targets and any
claim reporting deadline require review before becoming customer promises.

## How the architecture reduces losses

| Before an external action | After an external action |
|---|---|
| Validate exact scope and current quote | Reconcile authoritative order/payment evidence |
| Reserve budget across concurrent tasks | Recover the recorded operation instead of replanning it |
| Restrict merchants and connector capabilities | Keep payment, delivery and claim status separate |
| Isolate signing keys and payment secrets | Verify and deduplicate callbacks and reimbursement requests |
| Reject unsupported conditions or expired authority | Pause affected connectors when a defect is discovered |

The guarantee ledger is separate from the customer spending ledger. It tracks
entitlement, terms version, incident, eligibility, gross loss, recoveries,
net eligible loss, applicable cap, decision, appeal and payout status.
Monitor accumulated exposure by connector, software version and failure type.
One shared bug can affect many subscribers simultaneously.

## The economics we must validate

For a simplified month, the following stress-tests the alternative in which
Belay carries transaction losses itself:

```text
Expected claims per subscriber
  = eligible actions x eligible loss probability x average net paid claim

Contribution before fixed costs and capital
  = subscription revenue - variable operating costs - expected claims
```

Illustration only: USD 29 subscription revenue, USD 9 variable operating
cost, 20 eligible actions per month and USD 40 average net claim payment.
The payment assumption must be estimated after recoveries and applicable caps.

| Eligible loss probability per action | Expected claims per subscriber | Contribution before fixed costs and capital |
|---|---:|---:|
| 0.1 percent | USD 0.80 | USD 19.20 |
| 1 percent | USD 8.00 | USD 12.00 |
| 5 percent | USD 40.00 | USD -20.00 |

These are arithmetic scenarios for that alternative, not a price recommendation, an actuarial
model or evidence that the business is profitable. They omit fixed costs,
taxes, acquisition and capital needs. Monthly averages also hide delayed
claims, annual-cap effects and correlated failures. One defect producing
200 eligible USD 100 payouts requires USD 20,000, regardless of that month's
subscription receipts. This supports evaluating partner-backed transaction
protection. In the selected route, replace expected direct claim payments in
Belay's model with actual partner charges, retained obligations and claim
handling costs. No partner quote is available yet.

Collect exposure denominators, paid and unpaid claims, recoveries, support
cost, claim development and failures by version. A blocked purchase is not
an observed claim; its face value is not automatically money saved. The
repository's zero observed synthetic violations cannot price this promise.

## Why the name does not decide whether this is insurance

In New York, the substance of a contingent financial promise matters, and
including its cost in a membership fee is not a general exemption.
[Insurance Law 1101](https://www.nysenate.gov/legislation/laws/ISC/1101).
Massachusetts likewise defines insurance by the underlying promise and
consideration. [Chapter 175 Section 2](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXXII/Chapter175/Section2).

An own-service performance remedy deserves separate analysis from broad
merchant-fraud or non-delivery protection. A historical
[New York DFS warranty opinion](https://www.dfs.ny.gov/insurance/ogco2009/rg090901.htm)
explains that relationship-to-product and control-of-risk distinction. It
does not establish an exemption for Belay's proposed software guarantee.
Neither a small cap nor the word guarantee settles classification.

Have qualified counsel determine the route for the actual terms and launch
states before offering reimbursement. For broader risk transfer, establish
an appropriately authorized insurer and distribution arrangement. A partner
does not automatically remove sales or producer-licensing requirements; see
[Massachusetts producer licensing](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXXII/Chapter175/Section162I).

Performance guarantees backed by risk-transfer arrangements already exist
in AI, including [Munich Re aiSure](https://www.munichre.com/en/solutions/for-industry-clients/insure-ai.html).
Belay's differentiation must come from the workflow, execution controls,
service quality and supported economics. A guarantee label alone is not novel.
