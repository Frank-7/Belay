import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(
  new URL("../prototype/web/index.html", import.meta.url),
  "utf8",
);
const scripts = [...html.matchAll(/<script>\s*([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length, 1, "Run the actual page's inline application script");

function loadPage() {
  // Only the DOM operations used during startup and history rendering are
  // needed here. Fetch promises are controlled independently of DOM state.
  const elements = new Map(
    [...html.matchAll(/\bid="([^"]+)"/g)].map(([, id]) => [
      id,
      {
        textContent: "",
        innerHTML: "",
        hidden: id === "error",
        value: id === "scenario" ? "lost_ack" : "",
        listeners: new Map(),
        setAttribute() {},
        addEventListener(event, listener) {
          this.listeners.set(event, listener);
        },
      },
    ]),
  );
  const requests = [];
  const context = vm.createContext({
    document: {
      getElementById: (id) => elements.get(id),
      querySelectorAll: () => [],
    },
    fetch: (path) => {
      assert.equal(path, "/api/cases");
      return new Promise((resolve, reject) => {
        requests.push({
          succeed: (cases) => resolve({ ok: true, json: async () => ({ cases }) }),
          fail: (message) => resolve({
            ok: false,
            json: async () => ({ error: message }),
          }),
          reject,
        });
      });
    },
  });
  vm.runInContext(scripts[0][1], context, { filename: "prototype/web/index.html" });
  assert.equal(requests.length, 1, "Startup begins the first history request");
  return {
    requests,
    element: (id) => elements.get(id),
    refresh: () => elements.get("refresh").listeners.get("click")(),
  };
}

function exampleCase(id) {
  return {
    id: id.repeat(32),
    mode: "belay",
    scenario: "lost_ack",
    status: "pending",
    amount_cents: 5000,
    total_refunded_cents: 5000,
  };
}

test("an older success cannot remove cases from a newer history response", async () => {
  const page = loadPage();
  page.refresh();
  const original = exampleCase("a");
  const added = exampleCase("b");
  page.requests[1].succeed([added, original]);
  await setImmediate();
  assert.equal(page.element("count").textContent, "(2)");

  page.requests[0].succeed([original]);
  await setImmediate();
  assert.equal(page.element("count").textContent, "(2)");
  assert.ok(page.element("history").innerHTML.includes(added.id));
  assert.equal(page.element("error").hidden, true);
});

test("an obsolete HTTP error cannot replace a successful refresh with an alert", async () => {
  const page = loadPage();
  page.refresh();
  page.requests[1].succeed([exampleCase("b")]);
  await setImmediate();
  page.requests[0].fail("Old history request failed");
  await setImmediate();
  assert.equal(page.element("count").textContent, "(1)");
  assert.equal(page.element("error").hidden, true);
});

test("an obsolete connection failure is ignored while the newer request is pending", async () => {
  const page = loadPage();
  page.refresh();
  page.requests[0].reject(new Error("Old connection closed"));
  await setImmediate();
  assert.equal(page.element("error").hidden, true);
  page.requests[1].succeed([exampleCase("b")]);
  await setImmediate();
  assert.equal(page.element("count").textContent, "(1)");
});

test("a failure of the current refresh remains visible to the operator", async () => {
  const page = loadPage();
  page.requests[0].succeed([exampleCase("a")]);
  await setImmediate();
  page.refresh();
  page.requests[1].fail("Current history request failed");
  await setImmediate();
  assert.equal(page.element("error").hidden, false);
  assert.equal(page.element("error").textContent, "Current history request failed");
  assert.equal(page.element("count").textContent, "(1)");
});
