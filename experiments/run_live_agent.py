#!/usr/bin/env python3
"""Measure identical-input model decision divergence, outside the runtime.

Requires an OpenAI-compatible Chat Completions endpoint and a model that
supports temperature. Only Python's standard library is used; no repo code
is imported. API reference: https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create

Pilot (50 calls, one prompt, temperature 1):
    OPENAI_API_KEY=... python3 experiments/run_live_agent.py --reps 50
Then retain the pilot and sweep temperatures, without repeating its calls:
    python3 experiments/run_live_agent.py --reps 50 --resume \
        --temperatures 1 0 0.5 --prompts borderline clear_cut

Use --model / OPENAI_MODEL and --base-url / OPENAI_BASE_URL to select the
service; --api-key-env selects a different environment variable. Prompts
are fixed before calls and never adapted to observed divergence. An
existing result requires --resume, so raw evidence is not overwritten.

The primary rate treats unparseable as a third category. A second rate
conditions explicitly on parseable decisions. The all-pairs estimator is
unbiased for IID invocations; its overlapping pairs are NOT independent
trials. BELAY_NONDET_P is P(split), not the disagreement rate: the current
binary simulator's population disagreement probability is 2*p*(1-p).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ("full_refund", "split_refund_plus_credit", "unparseable")
SCHEMA_VERSION = 1
SYSTEM_PROMPT = """You handle customer refund requests for a retailer.
Choose a fair remedy based on the problem, the customer's preferences,
and the customer relationship. The order total is 5000 cents. You may use
one of these approved remedies:
- full_refund: refund 5000 cents to the original payment method, credit 0.
- split_refund_plus_credit: refund 3000 cents to the original payment
  method and issue 2000 cents of store credit.
Return only a JSON object with exactly one key, "decision", whose value
is one of those two labels. Do not include an explanation."""
PROMPTS = {
    "borderline": """Order R-1042 cost 5000 cents. It arrived three days late and
has a small cosmetic mark, but works as intended. The customer is
disappointed and asks for a fair adjustment. They would accept a refund
or a combination of refund and store credit, and expect to shop with us
again next month. Choose the remedy.""",
    "clear_cut": """Order R-1042 cost 5000 cents. It arrived damaged and cannot
be used. The damage is verified and the request is within the return
window. The customer explicitly requests all their money back to the
original payment method and does not want store credit because they do
not intend to shop with us again. Choose the remedy.""",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redact_secret(value: object, secret: str) -> object:
    """Remove a provider-echoed credential before persisting or printing it."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED_API_KEY]")
    if isinstance(value, list):
        return [redact_secret(item, secret) for item in value]
    if isinstance(value, dict):
        return {redact_secret(key, secret): redact_secret(item, secret)
                for key, item in value.items()}
    return value


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_decision(raw: str | None) -> str:
    """Strict, auditable: exact label, JSON string, or {decision: label}.

    Whitespace is ignored. Prose, fences, extra keys, conflicting answers,
    duplicate keys, nonstrings and unknown labels are unparseable.
    """
    if not isinstance(raw, str):
        return "unparseable"
    value = raw.strip()
    if value in LABELS[:2]:
        return value
    try:
        value = json.loads(value, object_pairs_hook=unique_object)
    except (ValueError, TypeError):
        return "unparseable"
    if isinstance(value, dict) and set(value) == {"decision"}:
        value = value["decision"]
    return value if isinstance(value, str) and value in LABELS[:2] else "unparseable"


def fraction(count: int, n: int) -> dict:
    return {"count": count, "n": n, "rate": count / n if n else None}


def disagreement(counts: dict[str, int]) -> dict:
    n = sum(counts.values())
    pairs = n * (n - 1) // 2
    same = sum(count * (count - 1) // 2 for count in counts.values())
    return {"n": n, "pairs": pairs, "disagreeing_pairs": pairs - same,
            "rate": (pairs - same) / pairs if pairs else None}


def summarize(cases: list[dict], conditions: list[dict], reps: int) -> dict:
    by_condition = []
    for condition in conditions:
        rows = [c for c in cases if c["condition_id"] == condition["id"]]
        responses = [c for c in rows if c["status"] == "model_response"]
        counts = {label: sum(c["decision"] == label for c in responses)
                  for label in LABELS}
        n = len(responses)
        valid = n - counts["unparseable"]
        p = counts["split_refund_plus_credit"] / valid if valid else None
        independent_pairs = n // 2
        # An odd final response has no partner in this independent-pair check.
        different = sum(responses[i]["decision"] != responses[i + 1]["decision"]
                        for i in range(0, n - 1, 2))
        usage: Counter = Counter()
        for row in responses:
            for key, value in (row.get("usage") or {}).items():
                if type(value) is int:
                    usage[key] += value
        by_condition.append({
            "condition_id": condition["id"],
            "prompt": condition["prompt"],
            "temperature": condition["temperature"],
            "requested_n": reps,
            "n": n,
            "attempts": len(rows),
            "api_errors": len(rows) - n,
            "counts": counts,
            "divergence": disagreement(counts),
            "parseable_decision_divergence": disagreement(
                {label: counts[label] for label in LABELS[:2]}),
            "unparseable": fraction(counts["unparseable"], n),
            "simulator_calibration": {
                "BELAY_NONDET_P": fraction(counts["split_refund_plus_credit"], valid),
                "population_disagreement_plugin": {
                    "n": valid, "rate": 2 * p * (1 - p) if p is not None else None,
                },
                "scope": "conditional on a parseable decision; simulator has no unparseable outcome",
            },
            "disjoint_pair_check": {
                "n_calls_used": independent_pairs * 2,
                "pairs": independent_pairs,
                "disagreements": different,
                "rate": different / independent_pairs if independent_pairs else None,
                "zero_events_upper_95_one_sided": (
                    1 - 0.05 ** (1 / independent_pairs)
                    if independent_pairs and different == 0 else None
                ),
            },
            "returned_models": sorted({c["returned_model"] for c in responses
                                       if c.get("returned_model")}),
            "system_fingerprints": sorted({c["system_fingerprint"] for c in responses
                                           if c.get("system_fingerprint")}),
            "usage": dict(usage),
        })
    return {"cases": len(cases), "responses": sum(c["n"] for c in by_condition),
            "by_condition": by_condition}


def write_result(path: Path, result: dict) -> None:
    """Checkpoint after each HTTP attempt; keep a previous result on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, delete=False) as fh:
            temporary = fh.name
            json.dump(result, fh, indent=2, ensure_ascii=False, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def invoke(endpoint: str, key: str, payload: bytes, timeout: float) -> dict:
    # HTTP is confined to this function in the opt-in experiment.
    from urllib.error import HTTPError, URLError
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = Request(endpoint, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    })
    started = time.monotonic()
    record = {"started_at": utc_now(), "status": "api_error", "raw_response": None,
              "http_status": None, "request_id": None, "error": None}
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            record["http_status"] = response.status
            record["request_id"] = response.headers.get("x-request-id")
            record["raw_response"] = response.read().decode("utf-8")
    except HTTPError as exc:
        record["http_status"] = exc.code
        record["request_id"] = exc.headers.get("x-request-id")
        record["raw_response"] = exc.read().decode("utf-8", errors="replace")
        record["error"] = f"HTTP {exc.code}; see retained raw_response"
    except (URLError, OSError, UnicodeError) as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc).replace(key, '[REDACTED]')}"
    record["elapsed_seconds"] = time.monotonic() - started
    if record["error"]:
        return record
    try:
        body = json.loads(record["raw_response"])
        if not isinstance(body, dict) or body.get("error"):
            raise ValueError("API error or nonobject envelope")
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("expected one choice")
        choice = choices[0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("missing assistant message")
        content = message.get("content")
        decision = parse_decision(content)
        if choice.get("finish_reason") != "stop" or message.get("refusal"):
            decision = "unparseable"
        record.update({
            "status": "model_response", "decision": decision,
            "raw_text": content, "finish_reason": choice.get("finish_reason"),
            "refusal": message.get("refusal"), "response_id": body.get("id"),
            "returned_model": body.get("model"), "system_fingerprint": body.get("system_fingerprint"),
            "usage": body.get("usage"),
        })
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        record["error"] = f"invalid API envelope: {exc}"
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=50, help="model responses per condition")
    ap.add_argument("--temperatures", "--temperature", type=float, nargs="+", default=[1.0])
    ap.add_argument("--prompts", nargs="+", choices=tuple(PROMPTS), default=["borderline"])
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini-2024-07-18"))
    ap.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    ap.add_argument("--max-completion-tokens", type=int, default=128)
    ap.add_argument("--reasoning-effort", help="optional model-specific setting, recorded verbatim")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "live_divergence.json")
    ap.add_argument("--resume", action="store_true", help="retain raw evidence and fill missing responses")
    args = ap.parse_args()
    if args.reps < 2 or args.max_completion_tokens < 1:
        ap.error("--reps must be >= 2 and --max-completion-tokens must be positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        ap.error("--timeout must be positive and finite")
    if any(not math.isfinite(t) or not 0 <= t <= 2 for t in args.temperatures):
        ap.error("temperatures must be finite numbers between 0 and 2")
    from urllib.parse import urlsplit
    parsed_url = urlsplit(args.base_url)
    if (parsed_url.scheme != "https" or not parsed_url.hostname
            or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment):
        ap.error("--base-url must be HTTPS, without credentials, query, or fragment")
    endpoint = args.base_url.rstrip("/") + "/chat/completions"
    config = {"model": args.model, "endpoint": endpoint,
              "max_completion_tokens": args.max_completion_tokens,
              "reasoning_effort": args.reasoning_effort,
              "system_prompt": SYSTEM_PROMPT, "prompts": PROMPTS,
              "parser": "strict-label-or-single-key-json-v1"}
    conditions = []
    for prompt in dict.fromkeys(args.prompts):
        for temperature in dict.fromkeys(args.temperatures):
            request = {"model": args.model, "temperature": temperature,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": PROMPTS[prompt]}],
                       "max_completion_tokens": args.max_completion_tokens,
                       "n": 1, "stream": False, "store": False}
            if args.reasoning_effort is not None:
                request["reasoning_effort"] = args.reasoning_effort
            conditions.append({"id": f"{prompt}@{temperature:g}", "prompt": prompt,
                               "temperature": temperature, "request": request,
                               "request_sha256": digest(encode(request))})
    result = {
        "summary": {}, "cases": [],
        "metadata": {
            "schema_version": SCHEMA_VERSION, "started_at": utc_now(),
            "status": "running", "configuration": config,
            "script_sha256": digest(Path(__file__).read_bytes()),
            "conditions": conditions,
            "method": {
                "sampling": "one fresh stateless HTTP request per invocation; byte-identical body within each condition; no fixed seed, retries, history, output cache, or adaptive prompts",
                "scheduling": "first condition completed first as pilot; remaining conditions interleaved by repetition",
                "divergence": "1 - sum(c_i*(c_i-1))/(n*(n-1)); all three parse categories; n is model responses, not pairs",
                "parseable_decision_divergence": "same estimator restricted explicitly to the two valid decisions",
                "unparseable": "invalid decision format, refusal, or non-stop finish; retained in primary denominator",
                "api_errors": "retained separately; stop immediately without replacing a failed call",
                "disjoint_pair_check": "consecutive nonoverlapping response pairs; if zero disagreements in m pairs, exact one-sided 95% binomial upper bound is 1 - 0.05**(1/m)",
                "simulator": "BELAY_NONDET_P is P(split), not P(disagree); population disagreement = 2*p*(1-p)",
            },
            "limitations": [
                "Synthetic fixed refund cases, not sampled production traffic; labels and option order are fixed.",
                "Rates apply only to the recorded model, prompt, settings, and observation window.",
                "IID stationary invocations are assumed, not established; returned model and fingerprint changes are retained.",
                "Overlapping all-pairs comparisons are not independent trials; zero observed divergence does not prove determinism.",
                "Unparseable is a single category; two unparseable texts can still differ in content.",
                "This measures model decisions, not recovery correctness or a production violation rate.",
            ],
        },
    }
    if args.out.exists():
        if not args.resume:
            ap.error(f"{args.out} exists; use --resume to preserve and extend it")
        with args.out.open(encoding="utf-8") as fh:
            result = json.load(fh)
        metadata = result["metadata"]
        if metadata["schema_version"] != SCHEMA_VERSION or metadata["configuration"] != config:
            ap.error("resume configuration differs; use a separate output for a different model or protocol")
        previous = {c["id"]: c for c in metadata["conditions"]}
        for condition in conditions:
            if condition["id"] in previous and condition != previous[condition["id"]]:
                ap.error("cannot change an existing condition's request")
            previous[condition["id"]] = condition
        conditions = list(previous.values())
        metadata["conditions"] = conditions
        metadata.setdefault("resumed_at", []).append(utc_now())
    elif args.resume:
        ap.error("--resume requires an existing result")
    metadata = result["metadata"]
    cases = result["cases"]
    completed = Counter(c["condition_id"] for c in cases if c["status"] == "model_response")
    if any(count > args.reps for count in completed.values()):
        ap.error("--reps cannot be smaller than a condition's retained sample size")

    def save(status: str, reason: str | None = None) -> None:
        metadata.update({"status": status, "updated_at": utc_now(),
                         "requested_reps_per_condition": args.reps, "stop_reason": reason})
        result["summary"] = summarize(cases, conditions, args.reps)
        write_result(args.out, result)

    key = os.environ.get(args.api_key_env, "").strip()
    if key and redact_secret(result, key) != result:
        ap.error("API key appears in public configuration or retained data; refusing to run")
    if not key and any(completed[c["id"]] < args.reps for c in conditions):
        reason = f"missing {args.api_key_env}; no live calls made"
        save("blocked_missing_credentials", reason)
        print(f"{reason}. Result written to {args.out}. Set the key and use --resume.", file=sys.stderr)
        return 2
    if not cases:
        metadata["script_sha256"] = digest(Path(__file__).read_bytes())
        metadata["started_at"] = utc_now()
    save("running")
    remaining = sum(args.reps - completed[c["id"]] for c in conditions)
    print(f"{remaining} calls remaining; model={args.model}; results={args.out}", flush=True)
    # Finish the first condition before spending calls on any sweep.
    schedule = [conditions[0]] * (args.reps - completed[conditions[0]["id"]])
    for rep in range(args.reps):
        schedule.extend(c for c in conditions[1:] if completed[c["id"]] <= rep)
    try:
        for condition in schedule:
            row = invoke(endpoint, key, encode(condition["request"]), args.timeout)
            redacted = redact_secret(row, key)
            if redacted != row:
                redacted["credential_redacted"] = True
            row = redacted
            row.update({"condition_id": condition["id"], "attempt": len(cases) + 1,
                        "rep": completed[condition["id"]] + 1,
                        "request_sha256": condition["request_sha256"]})
            cases.append(row)
            if row["status"] == "api_error":
                save("stopped_api_error", row["error"])
                print(f"Stopped: {row['error']}. Raw evidence saved to {args.out}.", file=sys.stderr)
                return 1
            completed[condition["id"]] += 1
            save("running")
            print(f"{condition['id']} {completed[condition['id']]}/{args.reps}: {row['decision']}", flush=True)
    except KeyboardInterrupt:
        save("interrupted", "interrupted; an in-flight call may have no captured response")
        print("Interrupted; completed responses retained.", file=sys.stderr)
        return 130
    save("complete")
    for cell in result["summary"]["by_condition"]:
        rate = cell["divergence"]["rate"]
        valid = cell["parseable_decision_divergence"]
        valid_text = f"{valid['rate']:.2%}" if valid["rate"] is not None else "unavailable"
        print(f"{cell['condition_id']}: divergence={rate:.2%} (n={cell['n']}); "
              f"valid-plan divergence={valid_text} (n={valid['n']}); "
              f"unparseable={cell['counts']['unparseable']}/{cell['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
