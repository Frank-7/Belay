.PHONY: help test test-second test-prototype prototype demo example matrix revocation adjudication \
        analyze checkdocs viewer all clean

PY ?= python3
REPS ?= 8

help:
	@echo "make test        42 contract assertions under real SIGKILL   (~30s)"
	@echo "make test-second 37 adjudicator assertions                    (~15s)"
	@echo "make test-prototype  portable Recovery Lab tests"
	@echo "make prototype      start the local Recovery Lab on port 8765"
	@echo "make demo        the divergence mechanism, annotated          (~10s)"
	@echo "make example     the pattern applied to another workflow      (~2s)"
	@echo "make all         matrix + revocation + analysis + viewer      (~3m)"
	@echo ""
	@echo "make matrix      REPS=$(REPS)  full crash matrix"
	@echo "make revocation  REPS=$(REPS)  permission revoked mid-flight"
	@echo "make adjudication             escalated anchors, adjudicated"
	@echo "make analyze     recompute every number quoted in FINDINGS.md"
	@echo "make checkdocs   fail if the doc tables disagree with results/"
	@echo "make viewer      rebuild viewer/trace.html"
	@echo "make clean       remove build artifacts (leaves results/ alone)"

test:
	$(PY) tests/test_contract.py

test-second:
	$(PY) tests/test_second.py

test-prototype:
	$(PY) -m unittest discover -s tests -p "test_prototype.py" -v

prototype:
	$(PY) -m prototype.server --port 8765

demo:
	$(PY) experiments/run_divergence.py

example:
	@echo "--- clean pass ---"
	$(PY) examples/minimal.py
	@echo "--- crash in flight, then recover ---"
	BELAY_CRASH_AT=in_flight $(PY) examples/minimal.py
	@echo "--- crash after intent, then recover ---"
	BELAY_CRASH_AT=after_intent $(PY) examples/minimal.py

matrix:
	$(PY) experiments/run_matrix.py --reps $(REPS)

revocation:
	$(PY) experiments/run_revocation.py --reps $(REPS)

adjudication:
	$(PY) experiments/run_adjudication.py --reps 4

analyze:
	$(PY) experiments/analyze.py

checkdocs:
	$(PY) experiments/check_docs.py

viewer:
	$(PY) viewer/build_viewer.py

all: test test-second test-prototype example matrix revocation adjudication analyze checkdocs viewer
	@echo ""
	@echo "done. open viewer/trace.html"

# `clean` removes build artifacts only. It deliberately leaves results/
# alone: those numbers are committed, the docs quote them, and
# `make checkdocs` verifies the two agree. Use `reset-results` if you
# really mean it.
clean:
	rm -rf viewer/trace.html
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete

reset-results:
	rm -rf results/*.json
	@echo "results/ cleared. Re-run 'make matrix revocation adjudication"
	@echo "analyze', then update the tables to match and confirm with"
	@echo "'make checkdocs'. The tables that move are:"
	@echo "  README.md and FINDINGS.md   the four-runtime matrix rows"
	@echo "  README.md, FINDINGS.md S8, docs/SECOND.md S6   adjudication"
	@echo "The figures that must NOT move are anchored's 0 violations and"
	@echo "the validated pipeline's 0 false resolutions."
