# Contributing

## The bar for a change

This repo makes measured claims, so a change has to keep them true.

```bash
make test        # must print: 42 passed, 0 failed
make test-second # evidence adjudicator assertions
make test-prototype # portable Recovery Lab tests
make test-recovery # evidence boundaries, model adapter, evaluation and demo
make test-live-experiment # decision experiment parser/retries; no API calls
make checkdocs   # committed results and documentation agree
ruff check .
```

The contract and end-to-end adjudicator suites require POSIX. On Windows,
run `python -m unittest discover -s tests -p "test_prototype.py" -v`,
`python tests/test_evidence_boundaries.py`, `python tests/test_live_agent.py`,
`python tests/test_evaluate_recovery.py`, `python tests/test_run_live_agent.py`
and `python experiments/check_docs.py`,
then verify the POSIX jobs in GitHub CI.
See [the integration guide](docs/INTEGRATION.md) for the separate runtime,
adjudicator and prototype boundaries.

For changes to the Recovery Lab frontend, also run its history regression
tests with Node.js 22 or newer (no dependencies to install):

```bash
node --test tests/test_prototype_ui.mjs
```

If you change anything under `belay/` or `services/`, also run:

```bash
make matrix REPS=8 && make revocation REPS=8 && make analyze
```

and check that `results/findings.json` still shows `anchored` at zero
violations and zero cents overpaid. If it does not, either the change is
wrong or CONTRACT.md needs revising — and revising the contract is a
legitimate outcome, provided FINDINGS.md is updated to match.

## Things worth working on

Listed in FINDINGS.md §9, roughly in order of value:

1. **Extend the live measurements.** `experiments/run_live_agent.py` contains
   decision-stability measurements, and `experiments/evaluate_recovery.py`
   compares evidence-recovery agents. Keep their questions separate, preserve
   prior runs, and distinguish incomplete samples from completed experiments.
2. **A lease.** The single-workflow-instance assumption is the weakest thing
   in CONTRACT.md. Invariant 1 does not hold without one.
3. **Unbounded effect slots.** Anchoring needs slots enumerated before the
   decision. Does it survive an agent that decides how many actions to take?
   If it does not, a clear negative result is more useful than a workaround.
4. **A new crash point.** `belay/chaos.py` has seven. If you find an
   instruction boundary that breaks an invariant, that is the most valuable
   possible contribution and it should be added to `CRASH_POINTS` with a
   failing test.

## House style

- **Runtimes are written out linearly, not factored.** `naive.py`,
  `replay_position.py`, `replay_content.py` and `anchored.py` duplicate
  structure on purpose, so a reader can diff them by eye. Please do not DRY
  them up.
- **Baselines are not strawmen.** Each one is the best version of a
  reasonable engineering instinct, and the comments say why someone would
  build it. Keep it that way; a rigged comparison is worth nothing.
- **Nothing under `belay/` may read the ledger.** `services/ledger.py` is the
  grading oracle. A runtime that can see it is no longer being tested.
- **State limitations in the docs, not in the code review.** If a change
  narrows or widens what we can claim, say so in FINDINGS.md §7.
