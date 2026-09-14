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
