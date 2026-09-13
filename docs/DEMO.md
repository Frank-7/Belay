# Belay recovery demo

Belay keeps an uncertain action paused until the available evidence supports
recovery. A model may propose where to look and explain its conclusion; the
validator checks the evidence, and the runtime controls the action.

The recovery desk runs real local worker processes and injects SIGKILL. Payments,
settlement reports, and webhooks are sandbox services. The browser displays a
recording of those executions. Its controls explore evidence and outcomes; they
do not issue payments or call a model.

## Run without credentials

Use Python 3.10+ on Linux, macOS, or Ubuntu in WSL:

```bash
python3 experiments/recovery_demo.py
python3 viewer/build_viewer.py --demo-json tmp-runs/recovery-demo.json
python3 -m http.server 8000 --bind 127.0.0.1 --directory viewer
```

Open `http://127.0.0.1:8000/trace.html`. The generated HTML also opens directly
from disk and can be shared as one file. `make recovery-demo` runs the first two
commands. A plain `python3 viewer/build_viewer.py` generates the default recorded
demo and the original five forensic scenarios.

On Windows, run the generation commands inside WSL. The web server can run in
PowerShell using `python` instead of `python3`.

The default agent is a deterministic heuristic. A deliberately unsupported
claim demonstrates rejection of stale evidence; it is labeled as an injected
claim, not represented as a real model hallucination. Neither demo generation
nor the default evaluation needs a network connection or an API key.

## Optional model run

Set `OPENAI_API_KEY` in the process environment, and set `OPENAI_MODEL` to a model
available to your account that supports Responses API Structured Outputs. Do
not put credentials in the repository, HTML, recordings, or command examples.

```bash
python3 experiments/recovery_demo.py --agent openai
python3 viewer/build_viewer.py --demo-json tmp-runs/recovery-demo.json
```

You can also supply the model with `--model`. A live run makes model requests
while generating the recording; opening its HTML later does not make requests.
Check the recording's agent label before presenting it. An API failure produces
an abstention, and does not silently become a successful heuristic result.
The recording is still saved for inspection, but the command exits with status
2 when model requests fail, or status 1 if a recovery violates the contract.

The adapter uses the [Responses Structured Outputs interface](https://developers.openai.com/api/docs/guides/structured-outputs).
Schema-conforming output remains an untrusted claim. Only retrieved evidence
can support a resolution; a model's confidence or prose cannot authorize it.
Pointers must name an advertised source inside the evidence directory and
request its manifest or exact current order. The validator also binds absence evidence to
the exact order; an empty result for a different order cannot authorize a refund.

## What to show in sixty seconds

| Time | Screen and narration |
|---|---|
| 0–10 seconds | A $50 sandbox refund has an uncertain outcome after a crash. Retrying blindly can issue a second refund. |
| 10–25 seconds | Show the paused workflow and its ledger total. Open the stale report: its cutoff does not cover the attempted action. |
| 25–40 seconds | Show why the verifier rejects the unsupported claim. Then inspect the covering report and the accepted resolution. |
| 40–50 seconds | Show the actual resumed outcome and payment count. Include the case where revoked permission prevents a new payment. |
| 50–60 seconds | State the current measurement, one limitation, and the next experiment. Identify whether this recording used the heuristic or a live model. |

Quote counts from the exact run being shown. Zero observed false resolutions
under this failure model is not a universal exactly-once guarantee. Evidence
sources are assumed truthful about their records and coverage, and workflows
still require a single active executor.

## Evaluate and share

```bash
python3 experiments/evaluate_recovery.py --out tmp-runs/recovery-evaluation.json
python3 tests/test_second.py
python3 tests/test_live_agent.py
python3 tests/test_evidence_boundaries.py
python3 tests/test_evaluate_recovery.py
python3 tests/test_recovery_demo.py
```

The evaluator reports false resolutions separately from abstentions and useful
resolutions. Use its optional OpenAI mode to compare a real model with the
heuristic on the same bounded sandbox cases. Report token usage and latency;
any dollar estimate requires explicit prices and is not a measured invoice.

GitHub Actions uploads `belay-evidence-<os>-py<version>` artifacts containing
the freshly generated experiments, evaluation, and standalone `trace.html`.
Download the artifact from the run page and share the HTML with judges. Access
to a private repository's Actions artifacts requires repository access; an
artifact upload does not publish a public website.

Rebuilding the demo leaves the committed research results untouched. The full
`make all` experiment pipeline regenerates those results and intentionally
checks their agreement with the published tables; random baseline changes can
require table updates. `make clean` preserves the results.

## Customer questions for the next checkpoint

Ask an operator of refund or other action-taking agents:

1. What happens today when a tool times out after the action might have succeeded?
2. Which records can establish that the action happened, or establish its absence?
3. Who investigates these cases, and how long does a typical case take?

Treat demand, avoided losses, and time savings as hypotheses until measured.
Keep the next product experiment focused on one workflow and its evidence
sources.
