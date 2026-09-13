# Belay autonomous app architecture

## Product decision

Build one app that completes tasks across supported services under authority
the user grants in advance. Concert tickets are the first demonstration;
paid research, shopping and other domains can reuse the execution system.

The user sets a goal, budget, allowed services, expiry and substitution rules.
Routine eligible actions proceed without another approval. An action pauses
when it needs new authority, required provider verification, or reliable
evidence of an uncertain outcome. The agent signs with its own delegated key.
It never receives the user's private signing key.

This supersedes the earlier blueprint's per-purchase approval default. The
architecture requires neither a custom smart contract nor a service that
holds customer funds pending delivery.

## System responsibilities

```mermaid
flowchart TD
    U[User sets goal and delegated scope] --> M[Mission interface]
    M --> P[Agent plans and researches]
    P --> A[Authority service checks proposed action]
    A --> B[Reserve budget and persist exact intent]
    B --> S[Protected signer]
    S --> E[Execution worker]
    E --> C[Approved merchant and payment adapters]
    C --> R[Receipts and reconciliation]
    R --> V[Activity and fulfillment view]
    R --> P
    R --> X[Pause unresolved actions]
```

| Component | Owns |
|---|---|
| Mission interface | Goal, success criteria, initial delegation and user controls |
| Planner | Research, comparison, tool choice and proposed actions |
| Authority service | Current permission, constraints, atomic budget reservations and signing requests |
| Protected signer | Protocol-specific signing with managed keys; no raw key access for the model |
| Execution worker | Stable action identity, saved intent, provider submission and supported retries |
| Adapters | Explicit capabilities, credentials, provider consistency and idempotency rules |
| Recovery service | Verified receipts, reconciliation, provider cancellation/refund recovery and unresolved states |

Keep one accountable executor initially. Specialist tools may make proposals
but cannot independently spend. Untrusted websites and tool outputs are data;
they cannot change a grant or instruct the signer.

## What standards and providers contribute

[AP2 v0.2](https://ap2-protocol.org/ap2/specification/) supplies a payment
authorization model. Open mandates delegate constrained authority; eligible
transaction-bound closed mandates can be signed using the agent key. Use a
maintained implementation, supported constraints and exact versioned profiles.
AP2 does not provide bank connectivity or merchant inventory APIs. Its current
specification leaves agent-to-agent mandate delegation outside scope.

Evaluate [Stripe Issuing for agents](https://docs.stripe.com/issuing/agents)
for autonomous spending, subject to program access and funding arrangements.
[Link spend requests](https://docs.stripe.com/agentic-commerce/link-cli/use-link-wallet-pay-online)
currently require customer approval before releasing credentials. AP2 cannot
override that requirement. Reading bank balances is a separate permission
from moving money; see [financial insights](https://docs.stripe.com/financial-connections/agents/financial-insights).

The merchant receives an approved payment credential through checkout and
its processor requests authorization. Track authorization, capture,
settlement and delivery separately. Card controls complement Belay's checks;
they do not validate exact seats or guarantee every final capture amount.
See [Stripe spending controls](https://docs.stripe.com/issuing/controls/spending-controls).

[Ticketmaster Discovery](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/)
provides event information and purchase links. Direct booking requires
appropriate [Partner API](https://developer.ticketmaster.com/products-and-docs/apis/partner/)
access. No such access is established here. The first checkout demo is simulated.

## Execution rules

1. Resolve missing requirements before starting autonomous work.
2. Obtain a current quote and validate seller, event, date, quantity, seats,
   all fees, expiry and the user's current scope.
3. Reserve budget atomically and persist an immutable operation and exact
   intent before requesting an external side effect.
4. Sign and submit through an approved adapter, using provider idempotency
   where supported. A changed quote requires validation again.
5. If the result is unknown, retain its reservation and reconcile the same
   operation. A lookup returning no record need not prove no purchase occurred.
6. Record verified outcomes and track fulfillment. A payment alone does not
   establish delivery. Refunds and cancellations are separate authorized actions.

Check current revocation before each new submission. This check is not atomic
with a remote commit: an in-flight purchase may still complete after revocation.
Revocation cannot recall a committed purchase. Reconciliation and support continue after expiry
or revocation under their appropriate access permissions.

Persist grants and versions, missions, offers, exact action payloads,
operation IDs, quote hashes, budget reservations, execution attempts,
provider IDs, receipts, exceptions and fulfillment state. Store credential
references rather than raw payment secrets in ordinary records.

## Where a proposed guarantee belongs

The guarantee service consumes execution evidence after an incident. It does
not relax purchase checks or give the planner access to reimbursement funds.
Keep subscription entitlement, guarantee terms, incident eligibility,
recoveries and claim payments in separate records. The operating app and
payment rails remain the same. See [the proposal](SUBSCRIPTION_GUARANTEE.md).

## Current implementation boundary

The existing Python Recovery Lab demonstrates a refund workflow against a
local fictional HTTP provider. It includes persisted state, crash scenarios,
reconciliation and an Activity view. Decisions and money are simulated.

The existing `second/` evidence adjudicator is a possible future source of
validated findings. Its `apply_dossier` can invoke `issue_effect`; do not
connect that completion path as an independent spender. Any app completion
must pass through the same authority, budget and execution service. Its
research journal and the lab's SQLite records are not interchangeable. See
[the integration guide](INTEGRATION.md).

The model planner, standing grants, production signer, domain adapters,
customer accounts and guarantee service are proposed. Start with one web
application, one worker and SQLite for the local demonstration. Production
requires durable deployment, account isolation, managed secrets, concurrency
controls, operational support and provider-specific integration review.
