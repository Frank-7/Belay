"""The second.

In climbing, the *second* is the one who belays the leader, then follows the
route and inspects every piece of protection the leader left behind. They
never lead, and they never place the gear the rope hangs on.

That is the whole architectural constraint of this package, and it is worth
stating before any code:

  * Nothing under `belay/` may import `second/`. The import direction *is*
    the guarantee. A nondeterministic component inside the recovery path
    would reintroduce exactly the bug this project exists to kill.
  * Nothing under `second/` may import `services.ledger`. The ledger is the
    grading oracle. An adjudicator that can read the answer key proves
    nothing. `tests/test_second.py` asserts both directions.

What this package does: `belay/runtimes/anchored.py` halts on an anchor it
cannot resolve (CONTRACT.md I3), and that halt is a dead end -- a human is
handed a hex string. The impossibility proof in CONTRACT.md S4 is about what
can be decided from inside the process, given only the journal and the
service API. It is not a proof that the fact is unknowable; out-of-band
records may still settle it.

So this package widens the input rather than weakening the contract. It
routes an agent at out-of-band evidence, verifies every pointer the agent
produces, and admits the retrieved artefact -- never the agent's summary of
it -- as a *query result* on the reconciliation ladder.

The agent is allowed to be nondeterministic, hallucinate, and be
overconfident, because its entire output surface is:

  1. **pointers** -- where to look. Deterministically fetched; an
     unfetchable pointer cannot be cited, so a fabricated one is inert.
  2. **a three-way verdict** -- committed / absent / abstain. Validated
     against the fetched observations; an unsupported verdict is forced to
     abstain.
  3. **prose** -- reasoning, for the human. Load-bearing for nobody.

It never names an anchor, an amount, or a scope. Those come from the
journal. The model chooses where to look; it does not get to invent effect
identities -- which is the same rule as `anchored.py` rule 1, one level up.
"""
