#!/usr/bin/env python3
"""Generate the crash forensics viewer.

Runs a fixed set of scenarios, captures each runtime's journal and the
ledger, and writes a single self-contained HTML file. No network, no build
step, no dependencies.

    python3 viewer/build_viewer.py && open viewer/trace.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import run_trial  # noqa: E402
from experiments.recovery_demo import generate_demo  # noqa: E402

ORDER_VALUE = 5000

SCENARIOS = [
    {
        "id": "lost_ack_cooperative",
        "name": "Lost acknowledgement, cooperative service",
        "blurb": "The refund committed. The process died before it heard back. "
                 "The payment service offers idempotency keys and a lookup.",
        "kw": dict(tier="idempotent", crash_at="in_flight", journal_decision=True,
                   force_plans=("full_refund", "full_refund")),
    },
    {
        "id": "lost_ack_opaque",
        "name": "Lost acknowledgement, no idempotency, no lookup",
        "blurb": "Same crash, but the service will not tell us whether our call "
                 "landed and will not dedupe a retry. Nobody can be correct here.",
        "kw": dict(tier="opaque", crash_at="in_flight", journal_decision=True,
                   force_plans=("full_refund", "full_refund")),
    },
    {
        "id": "diverged_decision",
        "name": "Decision diverges on recovery",
        "blurb": "The model chose a full refund, then chose a split refund on "
                 "restart. The service is the best tier available.",
        "kw": dict(tier="idempotent", crash_at="in_flight", journal_decision=False,
                   force_plans=("full_refund", "split_refund_plus_credit")),
    },
    {
        "id": "books_wrong",
        "name": "Effect durable, decision not",
        "blurb": "The refund is fully recorded when the crash lands. On restart "
                 "the model decides differently and recovery has to guess what "
                 "the journaled receipt belonged to.",
        "kw": dict(tier="idempotent", crash_at="after_effect_a_recorded",
                   journal_decision=False,
                   force_plans=("full_refund", "split_refund_plus_credit")),
    },
    {
        "id": "scope_revoked",
        "name": "Scope revoked while the workflow is down",
        "blurb": "An operator pulls the refund permission between the crash and "
                 "the restart. Nothing had committed yet.",
        "kw": dict(tier="idempotent", crash_at="after_intent",
                   revoke_scope="payments:refund",
                   force_plans=("full_refund", "full_refund")),
    },
]

# How each journal record kind is drawn.
KIND_STYLE = {
    "anchor": ("anchor", "effect identity allocated and fsynced"),
    "decided": ("decided", "decision persisted before use"),
    "inline_decision": ("inline", "decision used but never persisted"),
    "step_result": ("step", "journaled step result"),
    "intent": ("intent", "about to call the service under this anchor"),
    "settled": ("settled", "service confirmed and durably recorded"),
    "resolved": ("settled", "ambiguity settled against the service"),
    "refund_recorded": ("settled", "receipt recorded"),
    "credit_recorded": ("settled", "credit recorded"),
    "escalated": ("halt", "halted for a human"),
    "refused": ("halt", "declined before acting"),
    "committed": ("done", "runtime reports the workflow complete"),
    "attempt_start": ("boundary", "process boundary"),
    "divergence_observed": ("shadow", "divergence measured, not acted on"),
}


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    return out


def capture(base: str, scenario: dict) -> dict:
    lanes = []
    for rt in ORDER:
        t = run_trial(base, runtime=rt, keep=True, **scenario["kw"])
        records = sorted(
            read_jsonl(os.path.join(t.run_dir, "journal.jsonl"))
            + read_jsonl(os.path.join(t.run_dir, "trace.jsonl")),
            key=lambda r: r["ts"],
        )
        pids = []
        for r in records:
            if r["pid"] not in pids:
                pids.append(r["pid"])

        events = []
        for r in records:
            style, why = KIND_STYLE.get(r["kind"], ("step", r["kind"]))
            label = r.get("slot") or r.get("step") or ""
            amount = r.get("amount") or (r.get("plan") or {}).get("refund_cents")
            events.append({
                "kind": r["kind"],
                "style": style,
                "why": why,
                "pid_index": pids.index(r["pid"]),
                "label": label,
                "amount": amount,
                "anchor": (r.get("anchor") or "")[:8],
                "method": r.get("method", ""),
                "detail": _detail(r),
            })

        lanes.append({
            "runtime": rt,
            "verdict": t.verdict,
            "events": events,
            "n_processes": len(pids),
            "refunds": t.refund_amounts,
            "credit_amounts": t.credit_amounts,
            "total": t.total_returned_cents,
            "reported": t.reported_refund,
            "credits": t.n_credits,
            "notes": t.notes,
            "plan_first": t.plan_first_pass,
            "plan_last": t.plan_after_recovery,
        })
    return {**{k: scenario[k] for k in ("id", "name", "blurb")},
            "tier": scenario["kw"].get("tier"),
            "crash_at": scenario["kw"].get("crash_at"),
            "journal_decision": scenario["kw"].get("journal_decision", True),
            "revoked": scenario["kw"].get("revoke_scope"),
            "lanes": lanes}


def _detail(r: dict) -> str:
    bits = []
    for k in ("slot", "step", "amount", "method", "scope", "at", "reason",
              "journaled", "shadow", "diverged", "replaying", "durable"):
        if k in r and r[k] not in (None, ""):
            v = r[k]
            if isinstance(v, str) and len(v) > 60:
                v = v[:60] + "..."
            bits.append(f"{k}={v}")
    if "plan" in r and isinstance(r["plan"], dict):
        bits.append(f"plan={r['plan'].get('label')}")
    if "value" in r and isinstance(r["value"], dict):
        bits.append("value=" + ",".join(f"{k}:{v}" for k, v in r["value"].items()))
    return "  ".join(bits)


def script_json(value) -> str:
    """JSON for an inline script; never allow data to close the script tag."""
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c").replace(
        ">", "\\u003e"
    ).replace("&", "\\u0026")


def render_html(data: list[dict], demo: dict) -> str:
    if demo.get("schema_version") != 1 or not demo.get("cases"):
        raise ValueError("expected a recovery demo recording with schema_version 1 and cases")
    with open(os.path.join(ROOT, "viewer", "recovery_desk.css"), encoding="utf-8") as fh:
        css = fh.read()
    with open(os.path.join(ROOT, "viewer", "recovery_desk.js"), encoding="utf-8") as fh:
        js = fh.read()
    return (HTML.replace("__RECOVERY_CSS__", css)
            .replace("__RECOVERY_JS__", js)
            .replace("__DATA__", script_json(data))
            .replace("__DEMO__", script_json(demo)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-json", help="include a recorded heuristic or live-model demo")
    parser.add_argument("--out", default=os.path.join(ROOT, "viewer", "trace.html"))
    args = parser.parse_args()
    if args.demo_json:
        with open(args.demo_json, encoding="utf-8") as fh:
            demo = json.load(fh)
    else:
        print("recording recovery desk...")
        demo = generate_demo()
    with tempfile.TemporaryDirectory(prefix="belay-viewer-") as base:
        print("capturing forensic scenarios...")
        data = []
        for s in SCENARIOS:
            print(f"  {s['id']}")
            data.append(capture(base, s))

    out = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(data, demo))
    print(f"\nwrote {out}")
    return 0


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Belay | recovery desk</title>
<style>
  :root{
    --ground:#132029; --panel:#1b2c38; --panel2:#223744; --rule:#2b4256;
    --ink:#dce8f0; --dim:#7891a6;
    --anchor:#83b4e8; --settled:#5ed3a3; --ambiguous:#eda93f;
    --violation:#e2474c; --halt:#c2a3e8;
    --sans: ui-sans-serif, "Inter", "Helvetica Neue", Arial, sans-serif;
    --mono: ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo, Consolas, monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
       font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1180px;margin:0 auto;padding:40px 28px 96px}

  header{border-bottom:1px solid var(--rule);padding-bottom:22px;margin-bottom:30px}
  h1{font-size:15px;font-weight:600;letter-spacing:.16em;margin:0 0 6px;
     text-transform:uppercase;color:var(--dim)}
  .lede{font-size:26px;line-height:1.28;font-weight:400;max-width:30ch;margin:0}
  .lede b{font-weight:600;color:var(--anchor)}

  nav{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0 8px}
  button.tab{background:transparent;border:1px solid var(--rule);color:var(--dim);
    font-family:var(--sans);font-size:13px;padding:7px 13px;border-radius:2px;
    cursor:pointer;transition:none}
  button.tab:hover{border-color:var(--anchor);color:var(--ink)}
  button.tab[aria-pressed=true]{background:var(--anchor);border-color:var(--anchor);
    color:#0d1620;font-weight:600}
  button.tab:focus-visible{outline:2px solid var(--settled);outline-offset:2px}

  .scen{margin:22px 0 8px}
  .scen h2{font-size:19px;font-weight:600;margin:0 0 6px}
  .scen p{margin:0;color:var(--dim);max-width:70ch}
  .cond{display:flex;gap:22px;flex-wrap:wrap;margin-top:14px;
        font-family:var(--mono);font-size:12px;color:var(--dim)}
  .cond span b{color:var(--ink);font-weight:500}

  .board{margin-top:26px;border:1px solid var(--rule);background:var(--panel);
         border-radius:3px;overflow:hidden}
  .lane{display:grid;grid-template-columns:132px 1fr 150px;
        border-bottom:1px solid var(--rule);align-items:stretch}
  .lane:last-child{border-bottom:none}
  .lane-name{font-family:var(--mono);font-size:12px;padding:16px 12px;
    color:var(--dim);border-right:1px solid var(--rule);display:flex;
    align-items:center}
  .lane-name.ours{color:var(--anchor);font-weight:600}

  .track{position:relative;padding:16px 14px;display:flex;flex-wrap:wrap;
         gap:5px;align-items:center;min-height:58px}
  .seam{position:absolute;top:0;bottom:0;width:0;border-left:2px dashed var(--violation)}

  .ev{font-family:var(--mono);font-size:11px;padding:3px 7px;border-radius:2px;
      border:1px solid transparent;cursor:default;white-space:nowrap}
  .ev[data-s=anchor]{color:var(--anchor);border-color:var(--anchor)}
  .ev[data-s=settled]{color:var(--settled);border-color:var(--settled)}
  .ev[data-s=intent]{color:var(--ambiguous);border-color:var(--ambiguous)}
  .ev[data-s=decided]{color:var(--ink);border-color:var(--rule)}
  .ev[data-s=inline]{color:var(--ambiguous);border-color:var(--ambiguous);
    border-style:dashed}
  .ev[data-s=step]{color:var(--dim);border-color:var(--rule)}
  .ev[data-s=halt]{color:var(--halt);border-color:var(--halt)}
  .ev[data-s=done]{color:var(--dim);border-color:var(--rule)}
  .ev[data-s=shadow]{color:var(--dim);border-color:var(--rule);border-style:dotted}
  .ev[data-s=boundary]{display:none}
  .ev:hover{background:#0e1a22}

  .verdict{padding:16px 14px;border-left:1px solid var(--rule);
    display:flex;flex-direction:column;justify-content:center;gap:3px}
  .money{font-family:var(--mono);font-size:19px;font-weight:600}
  .money.bad{color:var(--violation)}
  .money.ok{color:var(--settled)}
  .money.held{color:var(--halt)}
  .vlabel{font-family:var(--mono);font-size:11px;color:var(--dim)}
  .delta{font-family:var(--mono);font-size:11px;color:var(--violation)}

  .readout{margin-top:18px;border:1px solid var(--rule);border-radius:3px;
    background:var(--panel);padding:18px}
  .readout h3{margin:0 0 10px;font-size:12px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--dim);font-weight:600}
  table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px}
  th{text-align:left;color:var(--dim);font-weight:500;padding:5px 10px 5px 0;
     border-bottom:1px solid var(--rule)}
  td{padding:5px 10px 5px 0;border-bottom:1px solid #22343f;color:var(--ink)}
  tr:last-child td{border-bottom:none}
  td.note{color:var(--dim);white-space:normal}

  .key{display:flex;flex-wrap:wrap;gap:16px;margin-top:26px;padding-top:20px;
    border-top:1px solid var(--rule);font-family:var(--mono);font-size:11px;
    color:var(--dim)}
  .key i{display:inline-block;width:9px;height:9px;margin-right:6px;
    border:1px solid currentColor;vertical-align:middle;font-style:normal}
  .detail{font-family:var(--mono);font-size:11px;color:var(--dim);
    padding:0 14px 14px;grid-column:2/3;min-height:0}
  @media (max-width:760px){
    .lane{grid-template-columns:1fr}
    .lane-name{border-right:none;border-bottom:1px solid var(--rule);padding:10px 12px}
    .verdict{border-left:none;border-top:1px solid var(--rule);flex-direction:row;
      gap:14px;align-items:baseline}
    .lede{font-size:21px}
  }
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
__RECOVERY_CSS__
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Belay &nbsp;/&nbsp; recovery desk</h1>
  <p class="lede">The agent lost its place.<br>The money <b>didn't.</b></p>
  <p class="header-note">Investigate an uncertain refund. Verify the evidence. Resume only when the record supports it.</p>
</header>

<section id="recovery" aria-label="Recorded recovery demonstration">
  <div class="recording-bar"><span class="recording-badge">Recorded execution</span><span>Sandbox payments</span><span id="agent-label"></span></div>
  <p class="desk-caption">Explore actual sandbox runs below. The buttons navigate the recording; payment actions happened during capture.</p>
  <nav id="recovery-cases" aria-label="Recovery cases"></nav>
  <div id="recovery-story"></div>
  <div class="desk-grid">
    <nav id="recovery-stages" aria-label="Recorded recovery steps"></nav>
    <article class="desk-card" id="recovery-step" aria-live="polite"></article>
  </div>
  <details class="assumptions"><summary>What this demonstration assumes</summary><div id="recovery-assumptions"></div></details>
</section>

<section class="forensics" aria-label="Original crash forensics">
<h2>Under the hood: crash forensics</h2>
<p class="desk-caption">Four runtimes face the same process death. Compare their journals with what the sandbox ledger actually recorded.</p>
<nav id="tabs" aria-label="Forensic scenarios"></nav>
<div class="scen" id="scen"></div>
<div class="board" id="board"></div>
<div class="readout" id="readout"></div>

<div class="key">
  <span style="color:var(--anchor)"><i></i>anchor allocated</span>
  <span style="color:var(--ambiguous)"><i></i>intent / not persisted</span>
  <span style="color:var(--settled)"><i></i>durably settled</span>
  <span style="color:var(--halt)"><i></i>halted for a human</span>
  <span style="color:var(--violation)">&#9553;&nbsp;&nbsp;crash seam</span>
</div>
</section>
</div>

<script>
const DATA = __DATA__;
const DEMO = __DEMO__;
const ORDER_VALUE = 5000;
let active = 0;

const money = c => "$" + (c/100).toFixed(2);

function drawTabs(){
  const nav = document.getElementById("tabs");
  nav.innerHTML = "";
  DATA.forEach((s,i)=>{
    const b = document.createElement("button");
    b.className = "tab";
    b.textContent = s.name;
    b.setAttribute("aria-pressed", i===active);
    b.onclick = ()=>{ active=i; draw(); nav.children[i].focus(); };
    nav.appendChild(b);
  });
}

function draw(){
  drawTabs();
  const s = DATA[active];

  document.getElementById("scen").innerHTML =
    `<h2>${s.name}</h2><p>${s.blurb}</p>
     <div class="cond">
       <span>service tier <b>${s.tier}</b></span>
       <span>crash point <b>${s.crash_at}</b></span>
       <span>decision persisted before use <b>${s.journal_decision}</b></span>
       ${s.revoked?`<span>scope revoked <b>${s.revoked}</b></span>`:""}
       <span>order value <b>${money(ORDER_VALUE)}</b></span>
     </div>`;

  const board = document.getElementById("board");
  board.innerHTML = "";
  s.lanes.forEach(l=>{
    const lane = document.createElement("div");
    lane.className = "lane";

    const name = document.createElement("div");
    name.className = "lane-name" + (l.runtime==="anchored" ? " ours" : "");
    name.textContent = l.runtime;
    lane.appendChild(name);

    const track = document.createElement("div");
    track.className = "track";
    let seamPlaced = false;
    l.events.forEach(e=>{
      if(e.pid_index>0 && !seamPlaced){
        const seam = document.createElement("div");
        seam.className = "seam";
        seam.style.position = "relative";
        seam.title = "process died here; a new process took over";
        track.appendChild(seam);
        seamPlaced = true;
      }
      if(e.style==="boundary") return;
      const chip = document.createElement("span");
      chip.className = "ev";
      chip.dataset.s = e.style;
      let txt = e.kind.replace(/_/g," ");
      if(e.label) txt += " " + e.label;
      if(e.amount) txt += " " + money(e.amount);
      chip.textContent = txt;
      chip.title = e.why + (e.detail ? "\n" + e.detail : "");
      track.appendChild(chip);
    });
    lane.appendChild(track);

    const v = document.createElement("div");
    v.className = "verdict";
    const held = l.verdict==="escalated" || l.verdict==="refused";
    const cls = l.total===ORDER_VALUE && !held ? "ok"
              : held ? "held" : "bad";
    const delta = l.total-ORDER_VALUE;
    v.innerHTML =
      `<div class="money ${cls}">${money(l.total)}</div>
       <div class="vlabel">${l.verdict.replace(/_/g," ")}</div>
       ${delta!==0?`<div class="delta">${delta>0?"+":""}${money(delta)} vs order</div>`:""}
       ${l.reported!==null && l.reported!==l.total
          ? `<div class="delta">reported ${money(l.reported)}</div>`:""}`;
    lane.appendChild(v);
    board.appendChild(lane);
  });

  const rows = s.lanes.map(l=>`
    <tr>
      <td>${l.runtime}</td>
      <td>${l.refunds.map(money).join(" + ") || "none"}</td>
      <td>${l.credit_amounts.map(money).join(" + ") || "none"}</td>
      <td>${l.plan_first||"-"}${l.plan_last&&l.plan_last!==l.plan_first?" &rarr; "+l.plan_last:""}</td>
      <td class="note">${(l.notes||[]).join("; ")||"-"}</td>
    </tr>`).join("");
  document.getElementById("readout").innerHTML =
    `<h3>Ledger: what the outside world actually recorded</h3>
     <table><thead><tr><th>runtime</th><th>refunds committed</th>
     <th>credits</th><th>decision</th><th>runtime's own account</th></tr></thead>
     <tbody>${rows}</tbody></table>`;
}
draw();
__RECOVERY_JS__
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
