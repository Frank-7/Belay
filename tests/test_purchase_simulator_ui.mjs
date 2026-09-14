import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(
  new URL("../purchase_simulator/web/index.html", import.meta.url),
  "utf8",
);
const script = readFileSync(
  new URL("../purchase_simulator/web/app.js", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../purchase_simulator/web/style.css", import.meta.url),
  "utf8",
);

test("investor view explains the product and labels every simulated boundary", () => {
  assert.match(html, /Agents can act[\s\S]*Belay makes them accountable/);
  assert.doesNotMatch(html, /pays any merchant|Every agent\. Any merchant/);
  assert.match(html, /USDC in · merchant gets USD/);
  assert.match(html, /No live money, coverage, chain, bank, merchant, model, or tickets/);
  assert.match(html, /Scenario protection reserve/);
  assert.match(html, /No financial product or live coverage/);
  assert.match(html, /Demo quote: 1 USDC = \$1\.00 · zero fees/);
});

test("money, reserve, status, receipt, and trace surfaces have stable unique IDs", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");
  for (const id of [
    "buyer-balance", "held-balance", "provider-balance", "merchant-balance",
    "reserve-cash", "reserve-committed", "reserve-pending", "reserve-paid",
    "funding-state", "conversion-state", "payout-state", "order-state",
    "delivery-state", "protection-state", "receipt", "trace-list", "payload",
  ]) {
    assert.ok(ids.includes(id), `missing investor surface #${id}`);
  }
  assert.equal((html.match(/class="receipt-grid"/g) || []).length, 1);
  for (const label of ["Instruction", "Purchase", "Payment", "Outcome"]) {
    assert.match(html, new RegExp(`>${label}<`));
  }
});

test("walkthrough uses native accessible controls and responsive motion hooks", () => {
  assert.match(html, /class="skip-link" href="#demo"/);
  assert.match(html, /role="progressbar"[^>]*aria-valuemin="0"[^>]*aria-valuemax="13"/);
  for (const id of ["start", "play", "next", "reset", "request-tab", "response-tab"]) {
    assert.match(html, new RegExp(`<button[^>]*id="${id}"[^>]*type="(?:submit|button)"`));
  }
  assert.match(html, /aria-live="polite"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /@media \(max-width: 720px\)/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /scroll-behavior: auto/);
});

test("browser calls only the local run API and renders payloads without innerHTML", () => {
  assert.match(script, /api\("\/api\/config"\)/);
  assert.match(script, /api\("\/api\/runs"/);
  assert.match(script, /budget_cents: 30_000/);
  assert.match(script, /expected_revision: run\.revision/);
  assert.match(script, /run\?\.payout_state === "unknown"/);
  assert.doesNotMatch(script, /\.innerHTML\s*=/);
  assert.match(script, /receipt\.outcome\.recovery_state/);
  assert.match(script, /needsReconciliation/);
  assert.doesNotMatch(script, /remedy · recovery open/);
  assert.match(script, /document\.createTextNode/);
  assert.match(script, /response_lost|Reconcile exact payout/i);
});
