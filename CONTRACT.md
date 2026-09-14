# Correctness contract

Everything this project claims is in this file. If a claim is not here, we
are not making it.

## 1. Failure model

What can go wrong, stated before any guarantee is offered.

| | |
|---|---|
| **Process** | May be killed at any instruction by SIGKILL. No unwinding, no `finally`, no flush. Anything not returned from `Journal.append` is lost. |
| **Journal** | Local append-only file, `fsync` per record. A record is durable once `append` returns. A torn tail record is treated as never having happened. |
| **External service** | Commits its effect and may die before the caller sees the acknowledgement. Never lies, never loses a committed effect, never reorders. |
| **Permissions** | Held outside the process. May change at any moment, including while the workflow is down. |
| **The agent** | Nondeterministic. Two invocations on identical inputs may return different decisions, and the decision determines control flow. |
| **Not modelled** | Byzantine services, clock skew, network partition of the journal, concurrent runs of the same workflow, machine-level power loss. See "Out of scope". |

The services differ in exactly one dimension, which turns out to decide
everything:

| Tier | Dedupes on a caller key | Answers "did attempt *k* commit?" |
|---|---|---|
| `idempotent` | yes | yes |
| `queryable` | no | yes |
| `opaque` | no | no |

## 2. Invariants

**I1 — At most one committed effect per anchored slot.**
For every effect slot in a workflow, the number of committed instances in
the external ledger is at most one, over any sequence of crashes and
restarts.

**I2 — No effect without a live permission.**
Every committed effect was authorised by a permission check that read the
permission store, and the check and the call are not separated by a
restart. An authorisation is never journaled as a replayable fact.

**I3 — Unresolved ambiguity halts.**
If the runtime cannot determine whether an anchored effect committed, it
halts and names the anchor. It does not retry, and it does not report
success or failure.

**I4 — Reports do not exceed reality.**
If the runtime reports a workflow committed with value *v*, the ledger
contains exactly that. A runtime that cannot say this truthfully must
report under I3 instead.

**I5 — An adjudication resolves only what evidence determines.**
If an anchor halted under I3 is later marked resolved, the journal contains
the digest and provenance of a retrieved artefact that entails the recorded
outcome. Absence is entailed only by silence from a source claiming
completeness over the window in which the effect may have been attempted;
silence from a lossy source entails nothing. An adjudication that cannot
meet this abstains, leaving the halt in place. I1, I2 and I4 hold through
the adjudicator unchanged: the completion rung is gated on proven absence,
it performs a live permission check immediately before acting, and a
resolution of "committed" requires a record matching the journaled intent.

I5 is about `second/`, which is not in the recovery path and is never
imported by `belay/`. The only thing crossing that boundary is a durable
journal record; see §5.1.

## 3. What makes I1 achievable: anchoring

Three rules, in `belay/runtimes/anchored.py`.

1. **Effect slots are enumerated and anchored before the model is
   consulted.** Each slot gets an opaque identifier, fsynced before the
   agent is called. The anchor is the effect's identity. The model chooses
   the *amount*; it does not get to invent effect identities. An effect
   with no anchored slot is refused.

2. **Recovery reads the journal; it does not re-derive intent by
   re-running.** The agent is re-invoked only when the journal proves no
   intent was ever durable, which means nothing external can have been
   attempted.

3. **Reconciliation separates queries from completions.** Asking a service
   what happened creates nothing and needs no permission. Issuing the
   effect because the query proved it never landed is a new effect and
   needs a live permission. Collapsing these two is a real bug; we shipped
   it and the harness caught it (FINDINGS.md).

The reason anchoring works is narrow and worth stating plainly: an
idempotency key derived from a nondeterministic decision inherits that
nondeterminism, and a key that is not stable across restarts is not an
idempotency key. An anchor allocated before the decision is stable by
construction.

## 4. An impossibility result

**Claim.** Let effect *E* target a service that offers neither dedupe on a
caller-supplied key nor any post-hoc query by which the caller can learn
whether a given attempt committed (the `opaque` tier). If the process may
be killed at an arbitrary instruction, then no runtime can guarantee both
at-least-once and at-most-once completion of *E*.

**Proof.** Consider two worlds at the moment of recovery. In *W₁* the
attempt never reached the service. In *W₂* it committed and the
acknowledgement was lost. The recovering process has two sources of
observation: its own journal, and whatever the service will tell it. The
journals are identical, because in both worlds the last durable record is
the intent and the crash preceded any settlement record. The service
observations are identical, because by assumption it exposes no query. So
*W₁* and *W₂* are indistinguishable under every observation available. No
decision rule can map them to different actions. Retrying commits twice in
*W₂*; halting completes never in *W₁*. ∎

This is elementary, and that is the point. The escalation in I3 is not
conservatism or a missing feature. It is the only behaviour consistent with
the information available. A runtime advertising exactly-once semantics
over an opaque service is advertising something the world does not contain.

**What the proof does not say.** Every clause of the claim is load-bearing,
and the scope is narrower than it first reads. The recovering process has
two sources of observation *because those are the two we granted it*: its
own journal, and the service API. The argument shows the fact is
undecidable from inside the process on that evidence. It does not show the
fact is unknowable. A settlement report, a webhook archive or a bank
statement may record what the service API will not disclose, and admitting
one of those is widening the input rather than defeating the proof.

§5.1 does exactly that, and the distinction survives measurement: given no
out-of-band records, the adjudicator resolves nothing at all, which is this
proof holding. Given a report whose coverage window excludes the attempt,
it also resolves nothing — silence is not absence unless something vouches
for the silence.

## 5. The guarantee we actually offer

> **Exactly-once up to escalation.**
> For every execution, under the failure model in §1: every anchored effect
> is committed at most once (I1), was authorised live (I2), and on
> termination either every anchored effect's status is known and recorded,
> or the runtime has halted naming the specific anchor whose status is
> unknown (I3). Reports never exceed the ledger (I4).

Availability is the price, and it is not hidden. The escalation rate is
measured per service tier in FINDINGS.md. On the `idempotent` and
`queryable` tiers it is zero: cooperation from the service buys back all
the availability. On the `opaque` tier it is 60%, and roughly a third of
those escalations page a human about an effect that never committed. That
residue is the impossibility in §4 expressed as an on-call burden.

### 5.1 Adjudication, and what it does and does not add

An escalation under I3 names an anchor and stops. `second/` takes that
record and searches out-of-band evidence for the fact the service would not
disclose, under I5. Two rungs, mirroring §3.3 and separated for the same
reason:

| rung | creates | permission |
|---|---|---|
| query out-of-band records | nothing | none required |
| complete, absence having been proved | a new effect | live check, at the instant of use |

Three properties make this safe to bolt onto a contract about money.

1. **It cannot enter the recovery path.** Nothing under `belay/` imports
   `second/`; `tests/test_second.py` asserts it by parsing the source. A
   nondeterministic component inside recovery would reintroduce the very
   failure §3 exists to remove.
2. **The agent's output surface is pointers, a three-way verdict, and
   prose.** It cannot name an anchor, an amount or a scope — those are read
   from the journaled intent. Pointers are fetched deterministically, so a
   fabricated pointer yields no observation and cannot be cited. Verdicts
   are checked against the observations actually fetched, so an unsupported
   verdict becomes an abstention.
3. **Abstention is a permitted terminal state**, because I3 already made it
   one. This is what makes the whole arrangement tractable: a wrong
   resolution is strictly worse than no resolution, so every ambiguity in
   the pipeline resolves toward silence.

Dossiers are scoped to the halted slot's relevant journal revision. Application
rejects a changed slot, an already closed anchor, or a proposal that predates a
new adjudication attempt. After an uncertain completion, fresh evidence must
cover that newer attempt. These are sequential-use checks under the existing
single-instance assumption; they do not coordinate concurrent executors.

The guarantee is therefore unchanged in form. What changes is that the
escalation in I3 is a floor rather than an endpoint: some halted anchors are
closed from evidence, the rest stay halted. FINDINGS.md §8 measures both,
including what the same agents do when their conclusions are not verified.

## 6. What is proved, what is measured, what is assumed

| | |
|---|---|
| **Proved** | §4, by an indistinguishability argument. |
| **Measured** | I1–I4 across 960 confirmed SIGKILLs, graded against the ledger rather than against the runtime's own report. Measurement is not proof; these are the invariants holding on the crash points we chose. |
| **Assumed** | The service never loses a committed effect. The journal's `fsync` is honest. Only one instance of a workflow runs at a time. Out-of-band evidence sources do not lie about their own coverage. |

## 7. Out of scope

Named so that nobody has to guess what we quietly skipped.

- **Concurrency.** One workflow instance at a time. Two processes recovering
  the same journal would need a lease; we have not built one, and I1 does
  not hold without it.
- **Machine failure.** Our crashes are SIGKILL to a process, so the OS page
  cache survives. Real power loss would test `fsync` in a way we do not.
- **Byzantine services.** A service that reports a commit it did not make
  breaks everything downstream of it, including the ladder in §3.3. The same
  applies to an evidence source under §5.1 that misstates its own coverage:
  a report claiming completeness it does not have will produce a confident
  false absence, and nothing in I5 detects that.
- **More than one effect slot of the same kind per order, under adjudication.**
  On the `opaque` tier the service received no caller key, so out-of-band
  records match on order and amount rather than on anchor. I5 requires the
  amount to match the journaled intent, which identifies the slot only while
  there is one refund slot per order. Two would need distinct amounts or a
  source carrying the client reference.
- **Compensation.** We classify effects as compensable or irreversible but
  never run a compensating transaction. The refund is irreversible on
  purpose: compensation is the escape hatch that makes these problems look
  easier than they are.
- **Model quality.** Whether the agent's refund decision is *correct* is a
  separate question from whether it was executed once and authorised. We
  make no claim about the former.

## 8. Operator application and testnet evidence

`recovery_app/` shares this journal and the `second/` validation/application
path. It serializes operations and holds an OS file lock for its data
directory. This prevents two local app instances sharing that directory;
it is not distributed coordination for arbitrary research-runtime workers.
Local scenarios perform SQLite operations with controlled missing
acknowledgments. Their application tests are separate from the historical
SIGKILL measurements and do not broaden their grader coverage.

The adjudicator now scans a bounded context independently of the model's
selected citations: up to eight sources, sixteen contextual reads and
sixteen proposed pointers. Malformed, unreadable or over-budget context
withholds resolution. Observable contradictions, including a matching
commit against a purportedly complete silent report, veto a supported
verdict. This detects some violations of the truthful-source assumption;
it cannot establish truth when all sources agree on a false account or
when relevant evidence is unavailable. It never treats model confidence
as a substitute for coverage.

The Arc adapter supports only Arc Testnet (5042002) and Circle's fixed USDC
ERC-20 interface. It verifies a transaction against the saved sender,
recipient, token, exact amount, transaction hash and pre-dispatch block
boundary. A successful canonical receipt must lie at or before the node's
finalized head and contain the matching token transfer event. These are
checks under the selected RPC and Arc consensus assumptions, not a
light-client or independently signed provider proof.

An Arc receipt is normalized to a **positive-only** recovery observation.
The demo permits 0.01–1.00 test USDC, so conversion to the existing integer
cent field is exact; the original six-decimal units and string transaction
hash are retained. A missing, pending, inconsistent or failed receipt
never produces permission to send a second transaction. Resolution records
an existing transfer or the exact finalized transaction's failed execution;
failed closure is a separate application journal record, not an absence
verdict. It retains the original hash and gas disclosure and requires fresh
verification of the same receipt and canonical block. A subsequent transfer
requires a separate intent and wallet authorization. The app has no blockchain signing or
broadcast callback. One transaction hash cannot resolve two app incidents.
The app refuses simultaneous unresolved cases with the same sender,
recipient and amount. Manual attachment must identify the original transfer:
the receipt proves a matching transfer after preparation, not a cryptographic
binding to a Belay order ID absent from the ERC-20 transaction.

MetaMask retains keys and asks the person to sign. Belay durably records
dispatch before requesting that signature, and a saved dispatch cannot be
sent again through the app. A browser failure before hash persistence
requires inspection and manual hash attachment. Revoking local permission
cannot cancel an already-open wallet prompt or undo a signed transaction;
the person must reject the prompt in MetaMask. This is human-authorized
testnet recovery, not autonomous custody, escrow or a financial guarantee.

## 9. Purchase investigation and USD evidence

The commerce simulator uses separate application and fictional-provider
databases. Before calling that provider, it commits an immutable dispatch
record and an uncertain state while retaining the customer hold. Recovery
looks up that same operation before expiry or cancellation can release funds.
An absent, unavailable or contradictory response leaves the hold reserved;
it never causes an automatic replacement submission. Accepted legacy
operations without the new dispatch record remain held for manual review.
These are local simulator guarantees, not bank, exchange or chain guarantees.

`purchase_simulator/recovery.py` translates the saved purchase and a read-only
provider lookup into `recovery_app/purchase.py`. Its versioned intent binds
the mission/run, grant, order, operation, quote and merchant beneficiary.
USDC six-decimal base units and USD cents have distinct fields. The adapter
does not invent a chain identity for fictional provider records or convert
the purchase into a research refund slot.

The investigator can return paid, unknown or conflicting evidence. Its
observations use the shared evidence citation format, while purchase-specific
checks validate the full settlement intent. This deterministic investigation
does not invoke the refund model or claim a live AI purchase. It has no
signing key, payment callback, bank client or reserve-payment authority.

The purchase engine alone can reconcile its ledger. It recomputes findings
from the persisted revision, verifies operation and intent identity, and
compares a fresh provider snapshot before applying them. Browser-supplied
findings cannot authorize reconciliation. Funding, conversion, USD payout,
delivery and reserve reimbursement remain distinct states. A payout receipt
does not establish ticket delivery, and a seeded demo reserve is not funded
production coverage.
