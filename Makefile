.PHONY: help test demo example matrix revocation analyze checkdocs viewer all clean

PY ?= python3
REPS ?= 8

help:
	@echo "make test        42 contract assertions under real SIGKILL   (~30s)"
	@echo "make demo        the divergence mechanism, annotated          (~10s)"
	@echo "make example     the pattern applied to another workflow      (~2s)"
	@echo "make all         matrix + revocation + analysis + viewer      (~3m)"
	@echo ""
	@echo "make matrix      REPS=$(REPS)  full crash matrix"
	@echo "make revocation  REPS=$(REPS)  permission revoked mid-flight"
	@echo "make analyze     recompute every number quoted in FINDINGS.md"
	@echo "make checkdocs   fail if the doc tables disagree with results/"
	@echo "make viewer      rebuild viewer/trace.html"
	@echo "make clean       remove build artifacts (leaves results/ alone)"

test:
	$(PY) tests/test_contract.py

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

analyze:
	$(PY) experiments/analyze.py

checkdocs:
	$(PY) experiments/check_docs.py

viewer:
	$(PY) viewer/build_viewer.py

all: test example matrix revocation analyze checkdocs viewer
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
	@echo "results/ cleared. Re-run 'make matrix revocation analyze', then"
	@echo "update the tables in README.md and FINDINGS.md to match, and"
	@echo "confirm with 'make checkdocs'."
