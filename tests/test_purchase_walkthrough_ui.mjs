import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const html = readFileSync(
  new URL("../purchase_simulator/web/purchase/index.html", import.meta.url),
  "utf8",
);
const script = readFileSync(
  new URL("../purchase_simulator/web/purchase/app.js", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../purchase_simulator/web/purchase/style.css", import.meta.url),
  "utf8",
);

test("investor story leads with one synchronized customer and backend simulation", () => {
  assert.match(html, /Let an agent buy[\s\S]*Keep every decision accountable/);
  assert.match(html, /Customer on the left[\s\S]*Infrastructure on the right/);
  assert.match(html, /CUSTOMER SEES/);
  assert.match(html, /BELAY PROVES/);
  assert.match(html, /Safe local simulation[\s\S]*No live chain, money, bank, merchant, wallet, coverage, model, or tickets/);
  assert.match(html, /Fictional local software demonstration · No financial product or live coverage/);
});

test("backend exposes trust, state, request, response, money, proof, and history surfaces", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");
  for (const id of [
    "customer-panel", "backend-panel", "customer-now", "backend-now",
    "buyer-balance", "held-balance", "provider-balance", "merchant-balance",
    "reserve-cash", "current-control", "current-money-effect", "current-proof",
    "current-retry", "policy-score", "control-groups", "funding-state",
    "conversion-state", "payout-state", "order-state", "delivery-state",
    "protection-state", "request-payload", "response-payload", "balance-changes",
    "latest-ledger-key", "proof-stack", "trace-list", "event-select", "return-live",
  ]) {
    assert.ok(ids.includes(id), `missing two-sided simulator surface #${id}`);
  }
  for (const label of ["CONTROL", "STATE / MONEY CHANGE", "PROOF CREATED", "SAFE REPLAY"]) {
    assert.match(html, new RegExp(`>${label}<`));
  }
});

test("controls are accessible and mobile swaps synchronized sides instead of stacking both", () => {
  assert.match(html, /class="skip-link" href="#simulator"/);
  assert.match(html, /aria-describedby="scenario-description"/);
  assert.match(html, /role="progressbar"[^>]*aria-valuemin="0"[^>]*aria-valuemax="13"[^>]*aria-valuenow="0"[^>]*aria-valuetext="Ready"/);
  for (const id of ["start", "play", "next", "reset", "view-customer", "view-backend", "return-live"]) {
    assert.match(html, new RegExp(`<button[^>]*id="${id}"[^>]*type="(?:submit|button)"`));
  }
  assert.match(html, /role="tablist" aria-label="Simulation side"/);
  assert.match(css, /\.workspace\[data-mobile-view="customer"\] \.backend-panel/);
  assert.match(css, /\.workspace\[data-mobile-view="backend"\] \.customer-panel/);
  assert.match(css, /@media \(max-width: 960px\)/);
  assert.match(css, /@media \(max-width: 720px\)/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /:focus-visible/);
});

test("browser follows one local event timeline and renders backend truth safely", () => {
  assert.match(script, /api\("\/api\/config"\)/);
  assert.match(script, /api\("\/api\/runs"/);
  assert.match(script, /budget_cents: 30_000/);
  assert.match(script, /expected_revision: run\.revision/);
  assert.match(script, /event\?\.user_message/);
  assert.match(script, /event\?\.accounts_after/);
  assert.match(script, /event\?\.balance_changes/);
  assert.match(script, /event\?\.ledger_keys/);
  assert.match(script, /provider_observation/);
  assert.match(script, /read_only_lookup_by_operation_id|Reconcile paid operation/);
  assert.match(script, /request-payload/);
  assert.match(script, /response-payload/);
  assert.match(script, /selectedButton\.offsetTop/);
  assert.match(script, /non_delivery_paid/);
  assert.doesNotMatch(script, /\.innerHTML\s*=/);
  assert.match(script, /document\.createTextNode/);
});

// Execute the actual browser handlers against a small DOM and controlled clock.
// These tests cover the paused state, not just the presence of a guard in source.
async function browserHarness(initialRun, replies = []) {
  let document;
  class Node {
    constructor() {
      this.children = [];
      this.handlers = {};
      this.dataset = {};
      this.style = {};
      this.attributes = {};
      this.disabled = false;
      this.value = "";
      this.textContent = "";
      this.classes = new Set();
      this.classList = {
        toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
        contains: (name) => this.classes.has(name),
      };
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    get lastElementChild() { return this.children.at(-1); }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    setAttribute(name, value) { this.attributes[name] = value; }
    querySelector() { return new Node(); }
    querySelectorAll() { return []; }
    focus() { document.activeElement = this; }
    scrollTo() {}
  }
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Node()]));
  document = {
    getElementById: (id) => { assert.ok(nodes.has(id), `missing DOM node ${id}`); return nodes.get(id); },
    createElement: () => new Node(),
    createTextNode: (value) => Object.assign(new Node(), { textContent: value }),
    createDocumentFragment: () => new Node(),
    querySelector: () => new Node(),
    querySelectorAll: () => [],
    addEventListener() {},
    activeElement: null,
  };
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  runInNewContext(script, {
    document,
    localStorage: { getItem: () => initialRun.id, setItem() {}, removeItem() {} },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    fetch: async (path, options) => {
      requests.push({ path, options });
      const response = path === "/api/config"
        ? { scenarios: [{ id: "timeout_reconcile", label: "Unknown payout" }], credentials: [] }
        : options?.method === "POST" ? replies.shift() : initialRun;
      assert.ok(response, `unexpected request ${path}`);
      return { ok: true, json: async () => response };
    },
  });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  await settle();
  return {
    nodes, requests, timers, settle,
    // Invoke the registered handler even when disabled, to cover a queued click.
    click: async (id) => { await nodes.get(id).handlers.click(); await settle(); },
  };
}

function playbackRun(extra = {}) {
  return {
    id: "a".repeat(32), scenario: "timeout_reconcile", revision: 7,
    operation_id: "purchase-operation-1",
    step: 7, stage: "payout_unknown", title: "Payout acknowledgment missing",
    payout_state: "unknown", terminal: false, can_advance: true, manual_review: false,
    events: [], ...extra,
  };
}

test("a restored unknown payout disables autoplay and keeps explicit reconciliation available", async () => {
  const h = await browserHarness(playbackRun(), [playbackRun({ revision: 8, payout_state: "paid" })]);
  assert.equal(h.nodes.get("play").disabled, true);
  assert.equal(h.nodes.get("play").attributes["aria-pressed"], "false");
  assert.equal(h.nodes.get("next").disabled, false);
  assert.match(h.nodes.get("next").children[0].textContent, /Reconcile/);
  await h.click("play");
  assert.equal(h.timers.size, 0);
  assert.equal(h.nodes.get("next").disabled, false);
  await h.click("next");
  const mutations = h.requests.filter(({ options }) => options?.method === "POST");
  assert.equal(mutations.length, 1);
  assert.deepEqual(JSON.parse(mutations[0].options.body), { expected_revision: 7 });
  assert.equal(h.timers.size, 0, "An explicit reconciliation must not restart autoplay");
});

test("automatic progression stops when a response becomes uncertain, including a queued timer", async () => {
  const h = await browserHarness(playbackRun({ payout_state: "submitted", stage: "payout_submitted" }), [playbackRun({ revision: 8 })]);
  await h.click("play");
  assert.equal(h.timers.size, 1);
  const queuedAdvance = [...h.timers.values()][0];
  await queuedAdvance();
  assert.equal(h.nodes.get("play").disabled, true);
  assert.equal(h.nodes.get("next").disabled, false);
  assert.equal(h.timers.size, 0);
  await queuedAdvance();
  assert.equal(h.requests.filter(({ options }) => options?.method === "POST").length, 1);
});

test("manual review cannot be resumed with autoplay", async () => {
  const h = await browserHarness(playbackRun({ payout_state: "paid", manual_review: true, can_advance: false, terminal: true }));
  assert.equal(h.nodes.get("play").disabled, true);
  await h.click("play");
  assert.equal(h.timers.size, 0);
  assert.equal(h.requests.filter(({ options }) => options?.method === "POST").length, 0);
});

test("uncertain original dispatch can still be reconciled without a payout finding", async () => {
  const h = await browserHarness(playbackRun({ step: 4, stage: "dispatch_unknown", funding_state: "dispatch_unknown" }));
  assert.equal(h.nodes.get("play").disabled, true);
  assert.equal(h.nodes.get("next").disabled, false);
  assert.match(h.nodes.get("next").children[0].textContent, /Reconcile original dispatch/);
  assert.equal(h.nodes.get("recovery-investigation").hidden, true);
});

function payoutFinding(extra = {}) {
  return {
    schema_version: "belay.purchase.investigation.v1",
    run_id: "a".repeat(32), revision: 7, operation_id: "purchase-operation-1",
    verdict: "paid", can_reconcile: true, summary: "The original USD payout matches.",
    checks: [{ label: "Merchant received USD", passed: true }],
    observations: [{ source: "USD provider receipt", digest: "test-digest", payload: { payout_state: "paid" } }],
    scope: "Fictional USD payout evidence; no money moved", ...extra,
  };
}

test("payout recovery shows read-only findings before allowing one explicit reconciliation", async () => {
  const h = await browserHarness(playbackRun({ step: 8 }), [payoutFinding(), playbackRun({ revision: 8, step: 9, payout_state: "paid" })]);
  assert.equal(h.nodes.get("recovery-investigation").hidden, false);
  assert.equal(h.nodes.get("next").disabled, true);
  assert.equal(h.nodes.get("investigate").disabled, false);
  await h.click("next");
  assert.equal(h.requests.filter(({ options }) => options?.method === "POST").length, 0);
  await h.click("investigate");
  assert.equal(h.nodes.get("investigation-verdict").textContent, "Paid");
  assert.equal(h.nodes.get("investigation-checks").children.length, 1);
  assert.equal(h.nodes.get("investigation-observations").children.length, 1);
  assert.equal(h.nodes.get("next").disabled, false);
  assert.equal(h.nodes.get("play").disabled, true);
  await h.click("next");
  assert.equal(h.nodes.get("recovery-investigation").hidden, true);
  assert.equal(h.nodes.get("investigation-verdict").textContent, "Awaiting evidence check", "Findings cannot survive a changed revision");
  assert.equal(h.timers.size, 0);
  const mutations = h.requests.filter(({ options }) => options?.method === "POST");
  assert.equal(mutations.length, 2);
  assert.match(mutations[0].path, /\/investigate$/);
  assert.match(mutations[1].path, /\/advance$/);
  for (const request of mutations) {
    assert.deepEqual(JSON.parse(request.options.body), { expected_revision: 7 }, "Never submit a client-controlled verdict to the backend");
  }
});

test("missing or contradictory payout evidence keeps reconciliation paused", async () => {
  for (const verdict of ["unknown", "conflict"]) {
    const h = await browserHarness(playbackRun({ step: 8 }), [payoutFinding({ verdict, can_reconcile: false })]);
    await h.click("investigate");
    assert.equal(h.nodes.get("next").disabled, true);
    assert.equal(h.nodes.get("play").disabled, true);
    await h.click("next");
    assert.equal(h.requests.filter(({ options }) => options?.method === "POST").length, 1);
  }
});

test("a finding for a stale revision or another operation cannot unlock reconciliation", async () => {
  for (const mismatch of [{ revision: 6 }, { run_id: "b".repeat(32) }, { operation_id: "another-payout" }]) {
    const h = await browserHarness(playbackRun({ step: 8 }), [payoutFinding(mismatch)]);
    await h.click("investigate");
    assert.equal(h.nodes.get("next").disabled, true);
    assert.match(h.nodes.get("error").textContent, /did not match this purchase revision/);
  }
});

test("an invalid saved intent displays its blocked reason without unlocking a payment", async () => {
  const h = await browserHarness(playbackRun({ step: 8 }), [payoutFinding({
    operation_id: null, verdict: "unknown", can_reconcile: false,
    summary: "The saved purchase intent cannot be verified.", checks: [], observations: [],
  })]);
  await h.click("investigate");
  assert.equal(h.nodes.get("next").disabled, true);
  assert.match(h.nodes.get("investigation-summary").textContent, /saved purchase intent cannot be verified/);
  assert.equal(h.nodes.get("error").hidden, true);
});

test("an in-flight investigation cannot be duplicated or reconciled before its response", async () => {
  let resolve;
  const pending = new Promise((yes) => { resolve = yes; });
  const h = await browserHarness(playbackRun({ step: 8 }), [pending]);
  const firstClick = h.click("investigate");
  await h.settle();
  assert.equal(h.nodes.get("investigate").disabled, true);
  assert.equal(h.nodes.get("next").disabled, true);
  await h.click("investigate");
  await h.click("next");
  assert.equal(h.requests.filter(({ options }) => options?.method === "POST").length, 1);
  resolve(payoutFinding());
  await firstClick;
  assert.equal(h.nodes.get("next").disabled, false);
});
