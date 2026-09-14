import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../purchase_simulator/web/index.html", import.meta.url), "utf8");
const script = readFileSync(new URL("../purchase_simulator/web/app.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../purchase_simulator/web/style.css", import.meta.url), "utf8");

test("product accepts one free-text mission without a canned scenario picker", () => {
  assert.match(html, /Tell your AI what to pay[\s\S]*Belay makes it safe/);
  assert.match(html, /id="request-input"[\s\S]*maxlength="1200"[\s\S]*required/);
  assert.match(html, /Build my payment plan/);
  assert.match(html, /id="example-list"/);
  assert.doesNotMatch(html, /id="scenario"|Choose the test|scenario-console/);
  assert.match(html, /id="simulate-lost-reply"/);
  assert.match(html, /href="\/purchase\/"/);
  assert.doesNotMatch(script, /\/api\/runs|non_delivery_paid|budget_cents/);
});

test("review includes an editable payment type and every money-moving field", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");
  for (const id of [
    "plan-form", "plan-category", "plan-description", "plan-payee", "plan-amount",
    "plan-maximum", "plan-reference", "plan-due-date", "save-plan",
    "authorize-payment", "authorization-card",
  ]) assert.ok(ids.includes(id), `missing payment review surface #${id}`);
  for (const category of ["purchase", "invoice", "bill", "tax", "insurance", "ticket", "subscription", "transfer"]) {
    assert.match(html, new RegExp(`<option value="${category}">`));
  }
  assert.match(script, /category: \$\("plan-category"\)\.value/);
  assert.match(script, /"plan-category"[\s\S]*\/details`, \{ expected_revision: mission\.revision, fields \}/);
  assert.match(html, /Belay never guesses the payee or amount/);
  assert.match(html, /Authorize &amp; pay now/);
});

test("pre-authorization view identifies the fictional recipient and fixed demo economics", () => {
  for (const id of ["beneficiary-id", "beneficiary-status"]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(script, /plan\.payee_id/);
  assert.match(script, /fictional_local_fixture/);
  assert.match(html, /Resets to 25,000 USDC/);
  assert.match(html, /1 USDC = \$1 USD/);
  assert.match(html, /Demo fee[\s\S]*\$0\.00/);
});

test("six visible policy groups account for all fifteen backend checks", () => {
  const backendCheckNames = [
    "User approved", "Plan unchanged", "Grant signature valid", "Payee matches",
    "Amount matches", "Within maximum", "Exact funds ready", "Reference ready",
    "Payee reviewed", "USDC source", "USD destination", "One-time scope",
    "Grant active", "Operation fixed", "Signed instruction matches",
  ];
  for (const name of backendCheckNames) assert.match(script, new RegExp(`"${name}"`));
  assert.equal((script.match(/\{ label: .*? names: \[/g) || []).length, 6);
  assert.match(script, /policy\?\.allowed === false && groups\.every/);
  assert.match(script, /passed === 15 && backendChecks\.length === 15/);
  assert.match(css, /\.check-item\.failed/);
});

test("proofs and receipt render backend evidence instead of UI counters", () => {
  assert.match(script, /Original request digest[\s\S]*mission\.request_digest/);
  assert.match(script, /Versioned payment plan[\s\S]*mission\.plan_revision/);
  for (const id of [
    "receipt-payee", "receipt-amount", "receipt-reference", "receipt-id",
    "receipt-limit", "receipt-date", "receipt-operation", "receipt-provider",
    "receipt-attempts", "receipt-authorization", "receipt-confirmation", "receipt-scope",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(script, /receipt\.payment\?\.provider_reference/);
  assert.match(script, /receipt\.payment\?\.attempt_count/);
  assert.match(script, /receipt\.authorization_digest/);
  assert.match(script, /receipt\.domain_outcome/);
});

test("customer and backend panes expose the same event, safe retry, money, and terminal state", () => {
  for (const id of [
    "customer-panel", "backend-panel", "backend-actor", "backend-action",
    "backend-explanation", "backend-proof", "backend-retry", "sync-label",
    "money-customer-value", "money-hold-value", "money-provider-value",
    "money-payee-value", "state-payload", "request-payload", "response-payload",
    "ledger-list", "event-list",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(script, /event\?\.backend\?\.proof/);
  assert.match(script, /event\?\.backend\?\.safe_retry/);
  assert.match(html, /Safe retry[\s\S]*id="backend-retry"/);
  assert.match(html, /Safe replay[\s\S]*id="safe-retry"/);
  assert.match(script, /Final linked state/);
  assert.match(script, /returned · no payout/);
  assert.match(script, /review_required/);
  assert.match(script, /mission\?\.status === "needs_details"/);
});

test("workflow uses revisioned APIs and a presentation-speed automatic run", () => {
  assert.match(script, /api\("\/api\/mission\/config"\)/);
  assert.match(script, /api\("\/api\/missions\/analyze", \{[\s\S]*demo_outcome:/);
  assert.match(script, /\/authorize`, \{ expected_revision: mission\.revision \}/);
  assert.match(script, /\/advance`, \{ expected_revision: mission\.revision \}/);
  assert.match(script, /const AUTO_DELAY_MS = 1900/);
  assert.match(script, /setTimeout\(\(\) => advanceOne\(true\), AUTO_DELAY_MS\)/);
  assert.match(script, /provider_payment\?\.attempt_count/);
});

test("mobile navigation is sticky, keyboard-operable, and returns to the customer", () => {
  assert.match(html, /role="tablist"[\s\S]*aria-orientation="horizontal"/);
  assert.match(html, /id="view-customer"[^>]*role="tab"[^>]*aria-controls="customer-panel"[^>]*tabindex="0"/);
  assert.match(html, /id="view-backend"[^>]*role="tab"[^>]*aria-controls="backend-panel"[^>]*tabindex="-1"/);
  assert.match(script, /setAttribute\("role", "tabpanel"\)/);
  assert.match(script, /\["ArrowLeft", "ArrowRight", "Home", "End"\]/);
  assert.match(script, /setMobileView\("customer"\);[\s\S]*scrollIntoView/);
  assert.match(script, /\$\("technical-audit"\)\.open = false;[\s\S]*setMobileView\("customer"\)/);
  assert.match(css, /\.product-navigation \{ position: sticky/);
  assert.match(css, /\.mobile-tabs button \{ min-height: 44px/);
  assert.match(css, /\.field input, \.field select \{[^}]*min-height: 44px/);
  assert.match(css, /@media \(max-width: 960px\)/);
  assert.match(css, /@media \(max-width: 720px\)/);
});

test("demo remains safe, accessible, and renders untrusted values as text", () => {
  assert.match(html, /class="skip-link" href="#mission"/);
  assert.match(html, /Never enter real SSNs, tax IDs, cards, bank details, API keys, wallet seeds, or policy credentials/);
  assert.match(html, /Fictional local product demonstration · No financial product, live payment, guarantee, or coverage/);
  assert.match(css, /\.workspace\[data-mobile-view="customer"\] \.backend-panel/);
  assert.match(css, /\.workspace\[data-mobile-view="backend"\] \.customer-panel/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /:focus-visible/);
  assert.doesNotMatch(script, /\.innerHTML\s*=/);
  assert.match(script, /document\.createTextNode/);
});

// Execute the shipped browser handlers with a minimal DOM and controlled network.
// No function is extracted or replaced: assertions observe requests and rendered controls.
class BrowserNode {
  constructor() {
    this.handlers = new Map(); this.attributes = new Map(); this.children = [];
    this.value = ""; this.textContent = ""; this.hidden = false; this.disabled = false;
    this.checked = false; this.dataset = {}; this.classList = { toggle() {}, add() {} };
  }
  addEventListener(type, handler) { this.handlers.set(type, handler); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  querySelectorAll() { return []; }
  closest() { return this; }
  focus() {}
  scrollIntoView() {}
  reportValidity() { return true; }
}
const missionId = "a".repeat(32);
const intentDigest = `sha256:${"b".repeat(64)}`;
function snapshot(extra = {}) {
  return {
    id: missionId, revision: 7, plan_revision: 1, operation_id: "operation-original",
    recovery_intent_digest: intentDigest, request_text: "Pay $20 to Acme", user_message: "Payout reply lost",
    status: "payout_unknown", stage: "payout_unknown", terminal: false,
    can_advance: false, can_authorize: false, can_investigate: true, demo_outcome: "payout_reply_lost",
    plan: { category: "transfer", payee: "Acme", amount_usd_cents: 2000, maximum_usd_cents: 2000,
      payee_id: "demo-acme", beneficiary_status: "fictional_local_fixture", review_notes: [] },
    grant: { expires_at: 1900000000 }, events: [], states: {},
    money: { customer_available_usdc_units: 24980000000, payment_hold_usdc_units: 0,
      provider_in_transit_usdc_units: 20000000, payee_received_usd_cents: 0 },
    ...extra,
  };
}
function finding(extra = {}) {
  return {
    schema_version: "belay.payment.investigation.v1",
    run_id: missionId, revision: 7, operation_id: "operation-original", intent_digest: intentDigest,
    evidence_digest: `sha256:${"c".repeat(64)}`, verdict: "paid", can_reconcile: true,
    summary: "Original operation paid the authorized USD amount.",
    checks: [{ label: "Exact operation and amounts", passed: true }], observations: [], citations: [], ...extra,
  };
}
async function flush() { for (let i = 0; i < 16; i++) await Promise.resolve(); }
async function browserHarness(savedMission = snapshot()) {
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new BrowserNode()]));
  const calls = [], pending = [], timers = new Map(), storage = new Map();
  let timerId = 0;
  if (savedMission) storage.set("belay.payment-mission.v1", savedMission.id);
  const context = {
    console, Intl, Date, Map, Set, Number, String, Boolean, JSON, Error,
    document: { getElementById: (id) => {
      assert.ok(nodes.has(id), `Script requested missing HTML element ${id}`); return nodes.get(id);
    }, createElement: () => new BrowserNode(), createTextNode: (text) => ({ textContent: text }),
    querySelectorAll: () => [], addEventListener() {} },
    window: { matchMedia: () => ({ matches: false }), addEventListener() {} },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    fetch: (path, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : undefined;
      calls.push({ path, body });
      if (path === "/api/mission/config") return Promise.resolve({ ok: true, json: async () => ({ examples: [] }) });
      if (!options.method && savedMission && path === `/api/missions/${savedMission.id}`) {
        return Promise.resolve({ ok: true, json: async () => structuredClone(savedMission) });
      }
      return new Promise((resolve) => pending.push({ path, body, resolve }));
    },
  };
  vm.runInNewContext(script, context, { filename: "purchase_simulator/web/app.js" });
  await flush();
  return {
    nodes, calls, pending, timers,
    postCount: () => calls.filter((call) => call.body !== undefined).length,
    async click(id, type = "click") {
      const promise = nodes.get(id).handlers.get(type)?.({ preventDefault() {} });
      await flush(); return { done: promise };
    },
    async reply(payload, status = 200) {
      const request = pending.shift(); assert.ok(request, "Expected pending HTTP request");
      request.resolve({ ok: status < 400, status, json: async () => structuredClone(payload) }); await flush();
    },
    async tick() {
      const entry = [...timers].find(([, timer]) => timer.delay === 1900);
      assert.ok(entry, "Expected automatic advance timer"); timers.delete(entry[0]); entry[1].fn(); await flush();
    },
  };
}

test("runtime: lost-reply mission pauses, investigates without mutation, then explicitly reconciles once", async () => {
  const h = await browserHarness(null);
  h.nodes.get("request-input").value = "Pay $20 to Acme";
  h.nodes.get("simulate-lost-reply").checked = true;
  await h.click("mission-form", "submit");
  assert.equal(h.pending[0].body.demo_outcome, "payout_reply_lost");
  await h.reply(snapshot({ status: "ready", stage: "plan_ready", can_authorize: true, can_investigate: false, grant: null }));
  await h.click("authorize-payment");
  await h.reply(snapshot({ status: "authorized", stage: "authorized", can_advance: true, can_investigate: false }));
  await h.tick();
  await h.reply(snapshot());
  assert.equal([...h.timers.values()].filter((timer) => timer.delay === 1900).length, 0);
  assert.equal(h.nodes.get("recovery-card").hidden, false);
  assert.equal(h.nodes.get("resume-payment").hidden, true);
  const before = h.postCount();
  await h.click("investigate-payment"); await h.click("investigate-payment");
  assert.equal(h.postCount(), before + 1, "Rapid clicks must share one investigation");
  assert.deepEqual(h.pending[0].body, { expected_revision: 7 });
  await h.reply(finding());
  assert.equal(h.nodes.get("recovery-verdict").textContent, "Payout evidence matches");
  assert.equal(h.nodes.get("reconcile-payment").hidden, false);
  assert.equal(h.postCount(), before + 1, "Finding never applies itself");
  await h.click("reconcile-payment"); await h.click("reconcile-payment");
  assert.deepEqual(h.pending[0].body, { expected_revision: 7, evidence_digest: finding().evidence_digest });
  await h.reply(snapshot({ revision: 8, stage: "paid", status: "paid", can_investigate: false, can_advance: true }));
  await h.tick();
  await h.reply(snapshot({ revision: 9, stage: "complete", status: "complete", terminal: true, can_investigate: false,
    receipt: { confirmation: "Payment complete", payee: "Acme", amount_usd_cents: 2000, payment: { attempt_count: 1 } } }));
  assert.equal(h.nodes.get("receipt-card").hidden, false);
  assert.equal(h.nodes.get("receipt-attempts").textContent, "1");
  assert.equal(h.calls.filter((call) => call.path.endsWith("/reconcile")).length, 1);
});

test("runtime: unknown, conflicting and failed-check findings never unlock reconciliation", async () => {
  for (const result of [finding({ verdict: "unknown", can_reconcile: false }), finding({ verdict: "conflict" }),
    finding({ verdict: "unknown", can_reconcile: false, evidence_digest: null, checks: [] }),
    finding({ checks: [{ label: "Authorized amount", passed: false }] }), finding({ checks: [] })]) {
    const h = await browserHarness();
    await h.click("investigate-payment"); await h.reply(result);
    assert.equal(h.nodes.get("reconcile-payment").hidden, true);
    await h.click("reconcile-payment");
    assert.equal(h.postCount(), 1, "No reconcile request for insufficient evidence");
  }
});

test("runtime: findings must match the mission, revision, operation and intent", async () => {
  for (const wrong of [{ run_id: "d".repeat(32) }, { revision: 6 }, { operation_id: "another-payment" },
    { intent_digest: `sha256:${"e".repeat(64)}` }, { evidence_digest: "missing-digest" }]) {
    const h = await browserHarness();
    await h.click("investigate-payment"); await h.reply(finding(wrong));
    assert.equal(h.nodes.get("recovery-finding").hidden, true);
    assert.equal(h.nodes.get("reconcile-payment").hidden, true);
    assert.match(h.nodes.get("product-error").textContent, /does not match/);
  }
});

test("runtime: missing original authority explains manual review without enabling reconciliation", async () => {
  const h = await browserHarness(snapshot({ recovery_intent_digest: null }));
  await h.click("investigate-payment");
  await h.reply(finding({ verdict: "unknown", can_reconcile: false, operation_id: null,
    intent_digest: null, evidence_digest: null, checks: [], summary: "The older provider record lacks captured authority. Manual review is required." }));
  assert.equal(h.nodes.get("recovery-verdict").textContent, "Evidence is incomplete");
  assert.match(h.nodes.get("recovery-summary").textContent, /Manual review/);
  await h.click("reconcile-payment");
  assert.equal(h.postCount(), 1);
});

test("runtime: stale reconcile conflict reloads current state and requires new evidence", async () => {
  const h = await browserHarness();
  await h.click("investigate-payment"); await h.reply(finding());
  await h.click("reconcile-payment");
  await h.reply({ error: "Evidence changed", current: snapshot({ revision: 8 }) }, 409);
  assert.equal(h.nodes.get("reconcile-payment").hidden, true);
  assert.equal(h.nodes.get("recovery-finding").hidden, true);
  await h.click("reconcile-payment");
  assert.equal(h.postCount(), 2);
  await h.click("investigate-payment");
  assert.equal(h.pending[0].body.expected_revision, 8);
});

test("runtime: investigation errors and uncertain reconciliation never trigger retries", async () => {
  const h = await browserHarness();
  await h.click("investigate-payment"); await h.reply({ error: "Provider unreadable" }, 503);
  assert.equal(h.nodes.get("reconcile-payment").hidden, true);
  await h.click("investigate-payment"); await h.reply(finding());
  await h.click("reconcile-payment"); await h.reply({ error: "Connection lost" }, 503);
  assert.equal(h.nodes.get("reconcile-payment").hidden, true);
  assert.equal(h.postCount(), 3);
  assert.equal([...h.timers.values()].filter((timer) => timer.delay === 1900).length, 0);
  assert.match(h.nodes.get("product-error").textContent, /Investigate again/);
});

test("runtime: reload and new requests cannot reuse findings from an older session", async () => {
  const h = await browserHarness();
  assert.equal(h.postCount(), 0);
  assert.equal(h.nodes.get("recovery-card").hidden, false);
  assert.equal(h.nodes.get("reconcile-payment").hidden, true);
  assert.equal(h.nodes.get("simulate-lost-reply").checked, true);
  await h.click("investigate-payment"); await h.reply(finding());
  await h.click("new-mission");
  await h.click("reconcile-payment");
  assert.equal(h.postCount(), 1);
  assert.equal(h.nodes.get("simulate-lost-reply").checked, false);
  assert.equal(h.nodes.get("product").hidden, true);
});
