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

## 6. What is proved, what is measured, what is assumed

| | |
|---|---|
| **Proved** | §4, by an indistinguishability argument. |
| **Measured** | I1–I4 across 960 confirmed SIGKILLs, graded against the ledger rather than against the runtime's own report. Measurement is not proof; these are the invariants holding on the crash points we chose. |
| **Assumed** | The service never loses a committed effect. The journal's `fsync` is honest. Only one instance of a workflow runs at a time. |

## 7. Out of scope

Named so that nobody has to guess what we quietly skipped.

- **Concurrency.** One workflow instance at a time. Two processes recovering
  the same journal would need a lease; we have not built one, and I1 does
  not hold without it.
- **Machine failure.** Our crashes are SIGKILL to a process, so the OS page
  cache survives. Real power loss would test `fsync` in a way we do not.
- **Byzantine services.** A service that reports a commit it did not make
  breaks everything downstream of it, including the ladder in §3.3.
- **Compensation.** We classify effects as compensable or irreversible but
  never run a compensating transaction. The refund is irreversible on
  purpose: compensation is the escape hatch that makes these problems look
  easier than they are.
- **Model quality.** Whether the agent's refund decision is *correct* is a
  separate question from whether it was executed once and authorised. We
  make no claim about the former.
