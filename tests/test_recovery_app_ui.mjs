import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

// Load the browser's dependency-free ES module without adding a package.json.
const source = readFileSync(new URL("../recovery_app/web/app.js", import.meta.url), "utf8");
const {createApi, createDeskController, canApply} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
function incident(id, revision = 1, extra = {}) {
  return {id, revision, status: "unresolved", title: id, proposal: {id: `${id}-proposal`, can_apply: true, verdict: "committed"}, ...extra};
}
function harness() {
  const requests = [];
  const api = Object.fromEntries(["get", "post"].map(method => [method, (path, body) => {
    const request = {...deferred(), method, path, body};
    requests.push(request);
    return request.promise;
  }]));
  const controller = createDeskController({api});
  return {controller, requests};
}
async function selectCase(h, value) {
  const result = h.controller.select(value.id);
  h.requests.at(-1).resolve(value);
  await result;
}

test("an older selected incident cannot replace the operator's current selection", async () => {
  const h = harness();
  const first = h.controller.select("first");
  const second = h.controller.select("second");
  h.requests[1].resolve(incident("second"));
  await second;
  h.requests[0].resolve(incident("first"));
  await first;
  assert.equal(h.controller.state.selected.id, "second");
  assert.equal(h.controller.state.loading, false);
});

test("an obsolete selection error cannot obscure a newer successful case", async () => {
  const h = harness();
  const first = h.controller.select("first");
  const second = h.controller.select("second");
  h.requests[1].resolve(incident("second"));
  await second;
  h.requests[0].reject(new Error("The old request failed"));
  await first;
  assert.equal(h.controller.state.selected.id, "second");
  assert.equal(h.controller.state.error, "");
});

test("an investigation finishing in the background updates history without switching cases", async () => {
  const h = harness();
  await selectCase(h, incident("first"));
  const investigation = h.controller.act("investigate", {agent: "heuristic"});
  const action = h.requests.at(-1);
  await selectCase(h, incident("second"));
  action.resolve(incident("first", 2));
  await investigation;
  assert.equal(h.controller.state.selected.id, "second");
  assert.equal(h.controller.state.incidents.find(item => item.id === "first").revision, 2);
  assert.equal(h.controller.state.busy, null);
});

test("duplicate clicks cannot send two resolutions while the first result is uncertain", async () => {
  const h = harness();
  await selectCase(h, incident("first"));
  const resolution = h.controller.act("resolve", {proposal_id: "first-proposal"});
  assert.equal(await h.controller.act("resolve", {proposal_id: "first-proposal"}), false);
  assert.equal(h.requests.filter(request => request.method === "post").length, 1);
  h.requests.at(-1).reject(new Error("Connection lost. Refresh to inspect the current record."));
  await resolution;
  assert.equal(h.requests.filter(request => request.method === "post").length, 1, "No automatic retry after a dropped acknowledgment");
  assert.match(h.controller.state.error, /Connection lost/);
  assert.equal(h.controller.state.selected.id, "first", "Retain the evidence after a failed request");
});

test("unsupported, already resolved and stale proposals cannot be applied from the UI", async () => {
  const h = harness();
  await selectCase(h, incident("first", 1, {proposal: {id: "unknown", can_apply: false}}));
  assert.equal(await h.controller.act("resolve", {proposal_id: "unknown"}), false);
  await selectCase(h, incident("first", 2));
  assert.equal(await h.controller.act("resolve", {proposal_id: "old-proposal"}), false);
  await selectCase(h, incident("first", 3, {status: "resolved"}));
  assert.equal(await h.controller.act("resolve", {proposal_id: "first-proposal"}), false);
  assert.equal(h.requests.filter(request => request.method === "post").length, 0);
  assert.equal(canApply(incident("first"), true), false);
});

test("an older refresh cannot erase a newly created incident", async () => {
  const h = harness();
  const refresh = h.controller.refresh();
  const creation = h.controller.create("lost_ack");
  h.requests[1].resolve(incident("new"));
  await creation;
  h.requests[0].resolve({incidents: []});
  await refresh;
  assert.equal(h.controller.state.incidents.length, 1);
  assert.equal(h.controller.state.selected.id, "new");
  assert.equal(h.controller.state.refreshing, false);
});

test("a late incident creation does not interrupt a deliberate selection", async () => {
  const h = harness();
  const creation = h.controller.create("lost_ack");
  const request = h.requests[0];
  await selectCase(h, incident("chosen"));
  request.resolve(incident("new"));
  await creation;
  assert.equal(h.controller.state.selected.id, "chosen");
  assert.ok(h.controller.state.incidents.some(item => item.id === "new"));
});

test("a late list response cannot downgrade the revision after resolution", async () => {
  const h = harness();
  await selectCase(h, incident("first"));
  const refresh = h.controller.refresh();
  const refreshRequest = h.requests.at(-1);
  const resolution = h.controller.act("resolve", {proposal_id: "first-proposal"});
  h.requests.at(-1).resolve(incident("first", 2, {status: "resolved"}));
  await resolution;
  refreshRequest.resolve({incidents: [incident("first", 1)]});
  await refresh;
  assert.equal(h.controller.state.incidents[0].status, "resolved");
  assert.equal(h.controller.state.selected.revision, 2);
});

test("an old receipt cannot appear under a newly selected incident", async () => {
  const h = harness();
  await selectCase(h, incident("first"));
  const receipt = h.controller.receipt();
  const request = h.requests.at(-1);
  await selectCase(h, incident("second"));
  request.resolve({id: "first", receipt: "sensitive-to-incident-context"});
  await receipt;
  assert.equal(h.controller.state.selected.id, "second");
  assert.equal(h.controller.state.receipt, null);
});

test("only the latest refresh may surface a failure", async () => {
  const h = harness();
  const old = h.controller.refresh();
  const current = h.controller.refresh();
  h.requests[1].resolve({incidents: [incident("current")]});
  await current;
  h.requests[0].reject(new Error("Obsolete failure"));
  await old;
  assert.equal(h.controller.state.error, "");
  assert.equal(h.controller.state.incidents[0].id, "current");
});

test("a recorded walkthrough reads fixtures and never sends a mutation", async () => {
  let networkCalls = 0;
  const api = createApi({recorded: true, fixtures: {config: {}, incidents: [incident("saved")]}, fetcher: () => {networkCalls++; throw new Error("Network should not run");}});
  const controller = createDeskController({api, recorded: true});
  await controller.start();
  assert.equal(controller.state.selected.id, "saved");
  assert.equal(await controller.act("resolve", {proposal_id: "saved-proposal"}), false);
  assert.equal(await controller.create("lost_ack"), false);
  await assert.rejects(api.post("/api/incidents", {}), /recorded walkthrough/);
  assert.equal(networkCalls, 0);
});

test("a live connection failure is shown, without substituting recorded data", async () => {
  const api = createApi({fetcher: async () => {throw new Error("Local server is unavailable");}});
  const controller = createDeskController({api});
  await controller.start();
  assert.equal(controller.state.recorded, false);
  assert.match(controller.state.error, /Local server is unavailable/);
  assert.equal(controller.state.incidents.length, 0);
});

test("the API exposes useful error text and makes each mutation only once", async () => {
  let attempts = 0;
  const api = createApi({fetcher: async () => {attempts++; return {ok: false, status: 409, json: async () => ({error: "The journal changed; investigate again."})};}});
  await assert.rejects(api.post("/api/incidents/first/resolve", {proposal_id: "old"}), /journal changed/);
  assert.equal(attempts, 1);
});

test("mismatched incident responses are rejected without installing another case", async () => {
  const h = harness();
  const selection = h.controller.select("wanted");
  h.requests[0].resolve(incident("wrong"));
  await selection;
  assert.equal(h.controller.state.selected, null);
  assert.match(h.controller.state.error, /did not match/);
});

test("opening a new incident prevents acting on the previous selection during creation", async () => {
  const h = harness();
  await selectCase(h, incident("old"));
  const creation = h.controller.create("lost_ack");
  const request = h.requests.at(-1);
  assert.equal(await h.controller.act("resolve", {proposal_id: "old-proposal"}), false);
  assert.equal(h.requests.filter(item => item.method === "post").length, 1);
  request.resolve(incident("new"));
  await creation;
  assert.equal(h.controller.state.selected.id, "new");
});

test("a read started before resolution cannot downgrade an opaque journal revision", async () => {
  const h = harness();
  await selectCase(h, incident("first", "hash-before"));
  const action = h.controller.act("resolve", {proposal_id: "first-proposal"});
  const actionRequest = h.requests.at(-1);
  const selection = h.controller.select("first");
  const selectionRequest = h.requests.at(-1);
  actionRequest.resolve(incident("first", "hash-after", {status: "resolved"}));
  await action;
  selectionRequest.resolve(incident("first", "hash-before"));
  await selection;
  assert.equal(h.controller.state.selected.revision, "hash-after");
  assert.equal(h.controller.state.selected.status, "resolved");
});
