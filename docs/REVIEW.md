# Belay evaluation — 12 September 2026

Reviewed the original repository at commit `7c68e95`. The product prototype
is an addition; the research runtime and committed experiment results have
not been repaired or regenerated in this change.

Handoff integration note: this prototype and review have now been combined
with main at `1fae768`. That main revision adds a research evidence adjudicator
and a Gemini decision-stability experiment. Neither connects a real planner
to the Recovery Lab or implements a customer guarantee. The journal and
anchor-initialization defects below remain in that revision. Its committed
live sample contains 150 responses with no observed decision divergence;
the synthetic divergent decisions in this lab are a different experiment.

## Verdict

Continue with **reliable execution and recovery of agent actions**, starting
with one refund workflow. The useful problem is concrete:

> An agent sends a business action, loses confirmation, and cannot tell
> whether it should retry. Belay preserves the original intent, checks
> external evidence, and stops when it cannot establish a safe next action.

This fits the earlier transaction-recovery idea. It is an execution component
and operator console around existing APIs. It is not a new payment rail,
A2A marketplace, fraud detector, or insurance product.

The repository has a substantive foundation: explicit failure assumptions,
four runtimes, crash injection, an independent ledger, permission-revocation
experiments, committed results and CI. The central behavior is testable.
The limitation is equally clear: one hard-coded refund/credit workflow,
simulated decisions, local providers, and no demonstrated paying customer.

## Concrete engineering findings

| Priority | Finding in original source | Consequence and next change |
|---|---|---|
| High | `belay/journal.py`, `Journal.read` stops at a torn tail, but `append` writes after it | Later successfully fsynced records become unreadable. Repair an incomplete tail before new writes; reject interior corruption and handle short writes. |
| High | `belay/runtimes/anchored.py`, anchor allocation can stop between slots; recovery does not complete allocation | Recovery can refund $30 and then raise `KeyError('credit')`. Finish valid initialization before deciding, reject inconsistent states, and test crashes between anchor writes. |
| Medium | `experiments/harness.py` counts fsyncs only from completed worker outcome files | Killed first-pass work is missing. The headline approximately 12% fsync overhead is not full-workflow accounting. Fix the metric before using it commercially. |
| Medium | The grader checks duplicate/refund reporting and refund revocation, not all credit outcomes | Zero reported violations does not cover every two-slot invariant. Grade credit amounts, duplicates, partial outcomes and credit-scope revocation too. |
| Integration | The queryable mock treats no lookup result as definitive absence | A real request can still be pending or absent from an eventually consistent index. Require provider finality, safe dedupe, or stop as unknown. |
| Integration | `_forward` reconstructs a plan from the current `PLANS` label | A changed deployment could execute parameters different from persisted intent. Execute validated, immutable stored parameters with a versioned schema. |

The first two findings were reproduced independently in constructed
persisted states. After a torn tail, a successful `decided` append disappeared
from `read()`. A journal with only the refund anchor produced a committed
3,000-cent refund followed by `KeyError('credit')` on split-plan recovery.
The latter reproduction disabled the unused crash helper inside a contained
child process on Windows; it was **not** a real SIGKILL experiment.

The prototype uses its own SQLite state rather than packaging the research
runtime as a safe library before those defects are fixed. Its tests are not
evidence that the defects above have been fixed.

## Narrow the public claims

- Report **zero observed violations at tested boundaries**, with the grader
  limitations above. Do not convert sampled synthetic outcomes into a
  proof about arbitrary failures or real customer incident rates.
- Qualify the cooperative-provider zero-escalation claim by decision
  persistence. FINDINGS reports 80% escalation with inline decisions.
- A live permission read is not atomic with a remote commit. Revocation
  can race between the check and the call. Read-only reconciliation can
  also require authentication and read permission; it need not require
  permission to create a fresh refund.
- The original $80-on-$50 example uses a permissive mock. Stripe refuses
  refunds beyond a charge's remaining unrefunded amount. The new prototype
  uses a $100 order and a $50 intent, so an unintended extra $30 fits the
  charge limit while still violating the intended action. [Stripe refund API](https://docs.stripe.com/api/refunds/create)

## What already exists

Temporal supports nondeterministic work, including model calls, through
recorded Activities. LangGraph documents persisting nondeterministic results
in tasks and making effectful operations idempotent. Correctly structured
durable workflows are an existing solution, not an impossible alternative.
[Temporal workflow definition](https://docs.temporal.io/workflow-definition),
[LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)

Stripe's existing idempotency protects retries under a stable key and checks
parameter consistency. Keys can be removed after at least 24 hours; storing
a local key does not extend the provider's deduplication lifetime. The lab
therefore includes a correct provider-idempotency baseline alongside the
unsafe new-key retry. [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)

Belay must earn adoption through easier integration, enforced intent
identity, accurate provider adapters and useful recovery operations. The
difficult work is supporting provider-specific failure behavior, concurrent
workers, expiring keys, deployments and understandable escalation. Adding
another prompt or another generic retry wrapper is insufficient.

## Next proof: one design partner, one workflow

Start with a support-automation or financial-operations team that already
lets agents issue refunds or account changes. The user's existing contacts
in payment/financial-services teams are a suitable route for interviews.

1. Ask for the most recent ambiguous action: request, logs, provider outcome,
   how the operator investigated it, and the time or money lost.
2. Establish what their correct idempotency and workflow implementation
   already handles, and where maintaining it becomes expensive.
3. Add one provider adapter in test mode. Exercise pending requests,
   conflicting parameters, revoked permission, key expiry and overlapping
   recoveries before considering live traffic.
4. Run a shadow pilot measuring investigation minutes, incorrect success
   reports, duplicate actions, unresolved cases, integration effort and
   added latency against the existing implementation.

There is no validated market size or willingness-to-pay estimate for this
specific product yet. The experiment proves that selected failure modes
can occur; it does not establish their commercial frequency. The initial
prototype is a way to obtain that evidence, not proof of a large business.
