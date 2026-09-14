import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../purchase_simulator/web/index.html", import.meta.url), "utf8");
const script = readFileSync(new URL("../purchase_simulator/web/app.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../purchase_simulator/web/style.css", import.meta.url), "utf8");

test("product accepts one free-text mission without a canned scenario picker", () => {
  assert.match(html, /Tell your AI what to pay[\s\S]*Belay makes it safe/);
  assert.match(html, /id="request-input"[\s\S]*maxlength="1200"[\s\S]*required/);
  assert.match(html, /Build my payment plan/);
  assert.match(html, /id="example-list"/);
  assert.doesNotMatch(html, /id="scenario"|Choose the test|scenario-console/);
  assert.doesNotMatch(html, /id="investigate"|recovery-investigation/);
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
  assert.match(script, /api\("\/api\/missions\/analyze", \{ request \}\)/);
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
