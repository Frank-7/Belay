/* Recovery Desk: model text and provider data are always rendered as text. */

export function incidentFrom(result) {
  const incident = result?.incident ?? result;
  if (!incident || typeof incident.id !== "string") throw new Error("The server returned an incomplete incident. Refresh the desk before continuing.");
  return incident;
}

export function isResolved(incident) {
  return ["resolved", "completed", "closed", "closed_from_evidence", "committed", "confirmed"].includes(incident?.status);
}

export function canApply(incident, recorded = false) {
  return !recorded && !isResolved(incident) && incident?.proposal?.can_apply === true
    && typeof incident.proposal.id === "string" && incident.proposal.id.length > 0;
}

export function statusLabel(status) {
  return ({prepared: "Ready for wallet approval", unresolved: "Needs investigation", pending: "Outcome uncertain", uncertain: "Outcome uncertain", unknown: "More evidence needed", held: "More evidence needed", needs_evidence: "More evidence needed", ready: "Ready for review", investigated: "Ready for review", resolved: "Resolved", completed: "Completed", closed: "Resolved", closed_from_evidence: "Verified from evidence", committed: "Transfer confirmed", confirmed: "Transfer confirmed", refused: "Permission revoked", revoked: "Permission revoked", failed: "Action failed"})[status] ?? String(status || "Outcome uncertain").replaceAll("_", " ");
}

export function createApi({fetcher = globalThis.fetch, recorded = false, fixtures = null} = {}) {
  async function request(path, options = {}) {
    if (recorded) {
      if (options.method && options.method !== "GET") throw new Error("This is a recorded walkthrough. Run the local Recovery Desk to investigate or apply a resolution.");
      if (path === "/api/config") return {...fixtures.config, mode: "recorded"};
      if (path === "/api/incidents") return {incidents: fixtures.incidents ?? []};
      const match = path.match(/^\/api\/incidents\/([^/]+)(\/receipt)?$/);
      const incident = match && fixtures.incidents?.find(item => item.id === decodeURIComponent(match[1]));
      if (incident) return match[2] ? (incident.receipt ?? {recorded: true, incident}) : incident;
      throw new Error("This incident is not part of the recorded walkthrough.");
    }
    const response = await fetcher(path, {
      ...options,
      headers: {Accept: "application/json", ...(options.body ? {"Content-Type": "application/json"} : {}), ...options.headers},
      cache: "no-store",
    });
    let body;
    try { body = await response.json(); }
    catch { throw new Error(response.ok ? "The server returned an unreadable response." : `The request failed (${response.status}). Refresh the desk to inspect the current state.`); }
    if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : (body.error?.message || body.message || `The request failed (${response.status}).`));
    return body;
  }
  return {get: path => request(path), post: (path, body = {}) => request(path, {method: "POST", body: JSON.stringify(body)})};
}

/* This controller is separate from the DOM so response ordering can be tested. */
export function createDeskController({api, onChange = () => {}, recorded = false}) {
  const state = {config: null, incidents: [], selected: null, selectedId: null, loading: false, refreshing: false, creating: false, busy: null, receipt: null, error: "", message: "", recorded};
  let selectionVersion = 0;
  let listVersion = 0;
  let actionVersion = 0;
  let dataVersion = 0;
  const recordVersions = new Map();
  const pending = new Set();
  const emit = () => onChange({...state, incidents: [...state.incidents]});
  const errorText = error => error instanceof Error ? error.message : String(error);
  function upsert(incident) {
    const existing = state.incidents.findIndex(item => item.id === incident.id);
    if (existing < 0) state.incidents.unshift(incident);
    else state.incidents[existing] = incident;
    recordVersions.set(incident.id, ++dataVersion);
  }
  function compatibleRevision(current, incoming) {
    if (!current || current.id !== incoming.id) return true;
    return !(Number.isFinite(current.revision) && Number.isFinite(incoming.revision) && incoming.revision < current.revision);
  }
  async function refresh() {
    const version = ++listVersion;
    state.refreshing = true;
    state.error = "";
    emit();
    try {
      const response = await api.get("/api/incidents");
      if (version !== listVersion) return false;
      const incidents = response.incidents ?? response;
      if (!Array.isArray(incidents)) throw new Error("The incident list could not be read.");
      state.incidents = incidents.map(item => {
        const local = state.incidents.find(old => old.id === item.id);
        return compatibleRevision(local, item) ? item : local;
      });
      return true;
    } catch (error) {
      if (version === listVersion) state.error = errorText(error);
      return false;
    } finally {
      if (version === listVersion) {state.refreshing = false; emit();}
    }
  }
  async function select(id) {
    const version = ++selectionVersion;
    const startedAtVersion = dataVersion;
    ++actionVersion;
    state.selectedId = id;
    state.selected = null;
    state.loading = true;
    state.busy = pending.has(id) ? "pending" : null;
    state.receipt = null;
    state.error = "";
    state.message = "";
    emit();
    try {
      const incident = incidentFrom(await api.get(`/api/incidents/${encodeURIComponent(id)}`));
      if (version !== selectionVersion) return;
      if (incident.id !== id) throw new Error("The incident response did not match your selection.");
      const local = state.incidents.find(item => item.id === id);
      state.selected = local && recordVersions.get(id) > startedAtVersion ? local : compatibleRevision(local, incident) ? incident : local;
      upsert(state.selected);
    } catch (error) {
      if (version === selectionVersion) state.error = errorText(error);
    } finally {
      if (version === selectionVersion) {state.loading = false; emit();}
    }
  }
  async function create(scenario) {
    if (state.creating || state.recorded) return false;
    state.creating = true;
    state.error = "";
    const version = selectionVersion;
    emit();
    try {
      const incident = incidentFrom(await api.post("/api/incidents", {scenario}));
      ++listVersion;
      state.refreshing = false;
      upsert(incident);
      if (version === selectionVersion) {
        ++selectionVersion;
        ++actionVersion;
        state.selected = incident;
        state.selectedId = incident.id;
        state.loading = false;
        state.receipt = null;
        state.busy = null;
        state.message = "Incident opened. Investigate the evidence to find the next step.";
      }
      return true;
    } catch (error) {
      state.error = errorText(error);
      return false;
    } finally {state.creating = false; emit();}
  }
  async function act(action, body = {}) {
    const id = state.selectedId;
    if (!id || !state.selected || state.recorded || state.busy || state.creating || pending.has(id)) return false;
    if (action === "resolve" && (!canApply(state.selected) || body.proposal_id !== state.selected.proposal.id)) return false;
    const selectedVersion = selectionVersion;
    const version = ++actionVersion;
    pending.add(id);
    state.busy = action;
    state.error = "";
    state.message = "";
    emit();
    try {
      const incident = incidentFrom(await api.post(`/api/incidents/${encodeURIComponent(id)}/${action}`, body));
      if (incident.id !== id) throw new Error("The action response did not match this incident. Refresh before continuing.");
      // Invalidate older list responses so a completed action cannot disappear.
      ++listVersion;
      state.refreshing = false;
      const local = state.incidents.find(item => item.id === id);
      if (compatibleRevision(local, incident)) upsert(incident);
      if (selectedVersion === selectionVersion && version === actionVersion && state.selectedId === id && compatibleRevision(state.selected, incident)) {
        state.selected = incident;
        state.receipt = null;
        state.message = ({investigate: "Investigation ready. Review the evidence and the proposed next step.", resolve: "Resolution recorded. Inspect the receipt for the outcome.", probe: "The new evidence is on the desk. Investigate again to review it.", revoke: "Permission revoked. Belay will check it before any new action."})[action] || "Incident updated.";
      }
      return true;
    } catch (error) {
      if (selectedVersion === selectionVersion && version === actionVersion) state.error = errorText(error);
      return false;
    } finally {
      pending.delete(id);
      if (state.selectedId === id) state.busy = null;
      emit();
    }
  }
  async function receipt() {
    const id = state.selectedId;
    if (!id || state.busy) return;
    const version = selectionVersion;
    state.busy = "receipt";
    state.error = "";
    emit();
    try {
      const result = await api.get(`/api/incidents/${encodeURIComponent(id)}/receipt`);
      if (version === selectionVersion) state.receipt = result;
    } catch (error) {
      if (version === selectionVersion) state.error = errorText(error);
    } finally {
      if (version === selectionVersion) {state.busy = null; emit();}
    }
  }
  async function start() {
    try {
      state.config = await api.get("/api/config");
      state.recorded = recorded || state.config.mode === "recorded";
      emit();
      await refresh();
      if (!state.selectedId && state.incidents.length) await select(state.incidents[0].id);
    } catch (error) {state.error = errorText(error); emit();}
  }
  return {state, start, refresh, select, create, act, receipt};
}

const text = value => typeof value === "string" ? value : (value == null ? "" : JSON.stringify(value));
const list = value => Array.isArray(value) ? value : (value == null ? [] : [value]);
const evidenceFor = incident => {
  const observations = list(incident?.evidence ?? incident?.observations ?? incident?.proposal?.observations ?? incident?.proposal?.evidence);
  const citations = list(incident?.proposal?.citations).filter(item => item && typeof item === "object" && item.payload);
  const seen = new Set();
  return [...observations, ...citations].filter((item, index) => {
    const key = `${item.pointer ?? item.id ?? index}:${item.digest ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
};
const money = cents => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"}).format(Number(cents || 0) / 100);
function el(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = text(content);
  if (className) node.className = className;
  return node;
}
function append(parent, tag, content, className) {const node = el(tag, content, className); parent.append(node); return node;}
function timeLabel(value) {
  if (value == null) return "";
  const date = new Date(typeof value === "number" ? (value < 1e12 ? value * 1000 : value) : value);
  return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}
function verdictTitle(verdict) {
  return ({committed: "The action already happened.", present: "The action already happened.", not_committed: "The record supports a new attempt.", absent: "The record supports a new attempt.", unknown: "The evidence is not enough yet.", abstain: "The evidence is not enough yet.", refused: "Permission has been withdrawn.", conflict: "These records need further review.", inconsistent: "These records need further review."})[verdict] || text(verdict || "Review the proposed explanation").replaceAll("_", " ");
}
function addFact(parent, label, value) {if (value === undefined || value === null || value === "") return; const row = append(parent, "div"); append(row, "dt", label); append(row, "dd", value);}
function addRaw(parent, value) {append(parent, "pre", JSON.stringify(value, null, 2));}
function sourceName(item, index) {
  if (item.title || item.label) return text(item.title || item.label);
  const source = item.payload?.source ?? item.source ?? item.pointer?.split(":")[0];
  const name = ({settlement_report: "Processor statement", processor_receipt: "Processor receipt", arc_finalized_receipt: "Finalized Arc receipt"})[source] ?? source?.replaceAll("_", " ");
  if (name) return `${name}${item.pointer?.endsWith(":manifest") ? " · coverage" : " · order record"}`;
  return text(item.id ?? `Evidence ${index + 1}`);
}
function explanationFor(incident, proposal) {
  if (proposal.verdict === "committed") return incident.provider === "arc" ? "A finalized receipt matches the approved transfer. Recording this result will not request another wallet signature." : "The provider record contains a matching refund for this order. Recording the result will not send a second refund.";
  if (proposal.verdict === "absent") return "A complete statement covers the request and contains no matching refund. Completing the original request still requires current permission.";
  const notes = list(proposal.validator_notes ?? proposal.notes).join(" ").toLowerCase();
  if (notes.includes("conflict")) return "The available sources disagree. Keep the action paused until the conflicting records have been reconciled.";
  if (incident.provider === "arc") return "The available chain evidence does not establish a completed transfer. Find the original transaction and its finalized receipt before considering any new action.";
  return "The available evidence does not establish whether this action happened. Keep the request paused and get an authoritative record covering the attempted action.";
}

export function mountDesk(controller, root = document) {
  const $ = id => root.getElementById(id);
  let agentId = "heuristic";
  let configured = false;
  let previousError = "";
  let lastRenderKey = "";
  const expandedEvidence = new Set();
  function render(state) {
    $("error").hidden = !state.error;
    $("error").textContent = state.error;
    if (state.error && state.error !== previousError) $("announcement").textContent = state.error;
    else if (state.message) $("announcement").textContent = state.message;
    previousError = state.error;
    if (!state.config && state.error) {
      $("mode-label").textContent = "Not connected";
      $("mode-notice").textContent = "The Recovery Desk is not connected. Start the local server and reload this page.";
    }
    $("refresh").disabled = state.refreshing;
    $("refresh").setAttribute("aria-busy", String(state.refreshing));
    $("incident-count").textContent = String(state.incidents.length);
    if (state.config && !configured) {
      configured = true;
      $("mode-label").textContent = state.recorded ? "Recorded walkthrough" : "Live local demo";
      $("mode-label").classList.toggle("recorded", state.recorded);
      $("mode-notice").classList.toggle("recorded", state.recorded);
      $("mode-notice").textContent = state.recorded
        ? "Recorded walkthrough. These are saved results from the Recovery Desk. This page makes no model, payment or wallet calls. Run the local app to investigate your own demo incidents."
        : "Live local workspace. The sample incidents use a simulated provider, and no real money moves. The optional wallet demo uses public test tokens with no monetary value.";
      $("footer-mode").textContent = state.recorded ? "Recorded evidence · Run locally to interact" : "Local research preview · No real funds";
      const agents = list(state.config.agents).length ? state.config.agents : [{id: "heuristic", label: "Evidence rules", available: true}];
      $("agent").replaceChildren();
      agents.forEach(agent => {
        const option = append($("agent"), "option", `${agent.label || agent.id}${agent.available === false ? " · not configured" : ""}`);
        option.value = agent.id;
        option.disabled = agent.available === false;
      });
      agentId = agents.find(agent => agent.available !== false)?.id || "heuristic";
      $("agent").value = agentId;
      $("investigation-controls").hidden = state.recorded;
    }
    const incidentList = $("incident-list");
    const focusedIncident = root.activeElement?.closest?.(".incident-item")?.dataset.incidentId;
    incidentList.replaceChildren();
    if (!state.incidents.length) append(incidentList, "p", state.refreshing ? "Loading incidents…" : "No incidents yet. Open a demo below.", "muted small");
    state.incidents.forEach(incident => {
      const button = append(incidentList, "button", undefined, "incident-item");
      button.type = "button";
      button.dataset.incidentId = incident.id;
      button.setAttribute("aria-current", String(state.selectedId === incident.id));
      append(button, "span", incident.title || incident.scenario || "Recovery incident", "incident-item-title");
      const meta = append(button, "span", undefined, "incident-item-meta");
      append(meta, "span", "", `mini-dot${isResolved(incident) ? " resolved" : ""}`);
      append(meta, "span", statusLabel(incident.permission?.active === false && !isResolved(incident) ? "revoked" : incident.status));
      button.addEventListener("click", () => controller.select(incident.id));
      if (focusedIncident === incident.id) button.focus({preventScroll: true});
    });
    const scenarioList = $("scenario-list");
    scenarioList.replaceChildren();
    list(state.config?.scenarios).forEach(scenario => {
      if (state.recorded) return;
      const button = append(scenarioList, "button", undefined, "scenario-button");
      button.type = "button";
      button.disabled = state.creating;
      append(button, "span", "+", "scenario-plus");
      const label = append(button, "span");
      append(label, "strong", scenario.title || scenario.id);
      append(label, "small", scenario.description);
      button.addEventListener("click", () => controller.create(scenario.id));
    });
    root.querySelector(".scenario-heading").hidden = state.recorded;
    $("empty-state").hidden = !!state.selected;
    $("incident-detail").hidden = !state.selected;
    $("workspace").setAttribute("aria-busy", String(state.loading));
    if (state.loading) {
      $("empty-state").querySelector("h2").textContent = "Opening the incident…";
      return;
    }
    if (!state.selected) {
      $("empty-state").querySelector("h2").textContent = "A clear next step starts here.";
      return;
    }
    const incident = state.selected;
    const intent = incident.intent ?? {};
    const proposal = incident.proposal;
    const disabled = !!state.busy || state.creating;
    $("incident-reference").textContent = `${incident.provider === "arc" ? "ARC TESTNET" : "RECOVERY INCIDENT"} / ${incident.id.slice(0, 10)}`;
    $("incident-title").textContent = incident.title || "An interrupted action";
    $("incident-description").textContent = incident.description || (incident.provider === "arc" ? "Inspect the wallet transaction before deciding what happened." : "The request was saved, but its outcome needs to be established.");
    $("incident-status").textContent = statusLabel(incident.permission?.active === false && !isResolved(incident) ? "revoked" : incident.status);
    $("incident-status").className = `status-badge${isResolved(incident) ? " good" : incident.permission?.active === false || ["refused", "revoked", "failed"].includes(incident.status) ? " bad" : ""}`;
    const stage = isResolved(incident) ? 3 : proposal ? 2 : 1;
    $("progress").replaceChildren();
    ["Intent saved", "Outcome uncertain", "Evidence reviewed", "Decision recorded"].forEach((label, index) => {
      const item = append($("progress"), "li", undefined, index < stage ? "done" : index === stage ? "current" : "");
      append(item, "span", index < stage ? "✓" : String(index + 1));
      append(item, "b", label);
      if (index === stage) item.setAttribute("aria-current", "step");
    });
    const amount = incident.provider === "arc" ? `${(Number(incident.wallet?.amount_units ?? intent.amount_units ?? Number(intent.amount_cents || 0) * 10000) / 1e6).toFixed(2)} test USDC` : intent.amount_cents != null ? money(intent.amount_cents) : "the approved amount";
    $("intent-summary").textContent = intent.summary || (incident.provider === "arc" ? `Transfer ${amount} to the approved recipient.` : `Refund ${amount}. Keep the original request intact.`);
    $("intent-facts").replaceChildren();
    addFact($("intent-facts"), incident.provider === "arc" ? "Recipient" : "Order", incident.provider === "arc" ? incident.wallet?.recipient ?? intent.recipient : intent.order_id ? `Order ${intent.order_id.slice(-8)}` : undefined);
    addFact($("intent-facts"), "Permission", incident.permission?.active === false ? "Revoked" : "Active for this request");
    addFact($("intent-facts"), "Scope", incident.provider === "arc" ? "This test transfer" : intent.scope === "payments:refund" ? "Refund this order" : intent.scope || "This action only");
    addFact($("intent-facts"), "Requested", timeLabel(intent.ts ?? incident.created_at));
    $("provider-note").textContent = incident.provider === "arc" ? "Arc public testnet · Test USDC has no monetary value. Your wallet signs; Belay does not custody funds." : "Local simulated provider · No money moves. The evidence and recovery decisions run in this app.";
    $("investigate").disabled = disabled || state.recorded || isResolved(incident) || incident.status === "prepared";
    $("investigate").textContent = state.busy === "investigate" ? "Investigating…" : proposal ? "Investigate again ↗" : "Investigate evidence ↗";
    $("agent").disabled = disabled || state.recorded || isResolved(incident);
    $("agent-note").textContent = state.recorded ? "The investigator and its result below were recorded during this run." : agentId === "openai" ? "A configured model proposes an explanation. Deterministic validation controls what can be applied." : "Evidence rules are a deterministic baseline. Select a configured model to compare an AI proposal.";
    const renderKey = `${incident.id}:${incident.revision ?? ""}:${JSON.stringify([incident.evidence, proposal, incident.timeline, incident.provider_evidence, incident.permission])}`;
    if (renderKey !== lastRenderKey) {
      if (!lastRenderKey.startsWith(`${incident.id}:`)) expandedEvidence.clear();
      renderEvidence(incident);
      renderProposal(proposal);
      renderTimeline(incident);
      lastRenderKey = renderKey;
    }
    renderDecision(incident, state);
    $("revoke").hidden = state.recorded || incident.permission?.active === false || isResolved(incident);
    $("revoke").disabled = disabled;
    $("permission-note").textContent = incident.permission?.active === false ? "Permission has been revoked. This does not undo an action that already happened." : "Permission is checked again before a new action. You can withdraw it while investigating.";
    $("load-receipt").disabled = disabled;
    $("load-receipt").textContent = state.busy === "receipt" ? "Loading receipt…" : state.receipt ? "Refresh receipt" : "Inspect receipt";
    const receiptContent = $("receipt-content");
    receiptContent.replaceChildren();
    if (state.receipt) {
      addRaw(receiptContent, state.receipt);
      const download = append(receiptContent, "button", "Download JSON", "button secondary small-button");
      download.type = "button";
      download.addEventListener("click", () => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(state.receipt, null, 2)], {type: "application/json"}));
        const link = el("a"); link.href = url; link.download = `belay-${incident.id}-receipt.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    }
  }
  function renderEvidence(incident) {
    const evidence = evidenceFor(incident);
    $("evidence-list").replaceChildren();
    $("evidence-count").textContent = String(evidence.length);
    if (incident.provider === "arc") {
      const chain = incident.provider_evidence;
      const proof = append($("evidence-list"), "div", undefined, "chain-proof");
      append(proof, "strong", chain?.status === "committed" ? "Transfer verified on Arc" : chain?.status === "failed" ? "The transaction failed on Arc" : "Original wallet transaction");
      if (chain?.reason) append(proof, "p", chain.reason);
      const hash = chain?.metadata?.transaction_hash ?? incident.wallet?.transaction_hash;
      if (typeof hash === "string" && /^0x[0-9a-fA-F]{64}$/.test(hash)) {
        const link = append(proof, "a", "View original transfer on ArcScan ↗");
        link.href = `https://testnet.arcscan.app/tx/${hash}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      } else append(proof, "p", "Attach the original transaction hash from MetaMask to inspect its public receipt.");
      if (chain?.metadata?.block_number != null) append(proof, "small", `Block ${chain.metadata.block_number}${chain.metadata.finality ? ` · ${text(chain.metadata.finality)}` : ""}`);
    }
    if (!evidence.length) append($("evidence-list"), "p", "Run an investigation to bring the available records onto the desk.", "small muted");
    evidence.forEach((item, index) => {
      const details = append($("evidence-list"), "details", undefined, "evidence-item");
      details.id = `evidence-${index}`;
      const key = String(item.pointer ?? item.id ?? index);
      details.open = expandedEvidence.has(key);
      details.addEventListener("toggle", () => details.open ? expandedEvidence.add(key) : expandedEvidence.delete(key));
      append(details, "summary", sourceName(item, index));
      const body = append(details, "div", undefined, "evidence-body");
      if (item.description || item.summary) append(body, "p", item.description || item.summary);
      const matches = item.payload?.matches;
      if (Array.isArray(matches)) append(body, "p", matches.length ? `${matches.length} matching record${matches.length === 1 ? "" : "s"}${matches[0].amount_cents != null ? ` · ${money(matches[0].amount_cents)}` : ""}.` : "No matching records in this source.");
      if (item.payload?.coverage?.cutoff_ts != null) append(body, "p", `Coverage through ${timeLabel(item.payload.coverage.cutoff_ts)}.`);
      if (item.pointer) append(body, "code", item.pointer);
      addRaw(body, item.payload ?? item.record ?? item);
    });
  }
  function renderProposal(proposal) {
    const node = $("proposal");
    node.hidden = !proposal;
    node.replaceChildren();
    if (!proposal) return;
    append(node, "div", "PROPOSED EXPLANATION", "proposal-label");
    append(node, "h4", verdictTitle(proposal.verdict));
    append(node, "p", explanationFor(controller.state.selected, proposal));
    const details = append(node, "details", undefined, "validation-details");
    append(details, "summary", "How this was checked");
    list(proposal.reasoning ?? proposal.explanation ?? proposal.summary).forEach(reason => append(details, "p", reason));
    const notes = list(proposal.validator_notes ?? proposal.notes);
    if (notes.length) {
      const checks = append(details, "ul", undefined, "validator-notes");
      notes.forEach(note => append(checks, "li", typeof note === "string" ? note : (note.message ?? note.detail ?? text(note)), proposal.can_apply ? "" : "blocked"));
    }
    const citedKeys = new Set();
    const citations = list(proposal.citations).filter(item => {
      const key = typeof item === "string" ? item : `${item.pointer ?? item.id ?? item.source}:${item.digest ?? ""}`;
      if (citedKeys.has(key)) return false;
      citedKeys.add(key); return true;
    });
    if (citations.length) {
      const links = append(node, "div", undefined, "citation-links");
      citations.forEach((citation, index) => {
        const pointer = typeof citation === "string" ? citation : (citation.pointer ?? citation.source ?? citation.id ?? "");
        const evidence = evidenceFor(controller.state.selected);
        const match = evidence.findIndex(item => [item.pointer, item.id, item.source, item.digest].includes(pointer));
        const label = citation?.label ?? (match >= 0 ? sourceName(evidence[match], match) : `Source ${index + 1}`);
        const link = append(links, "button", `↗ ${label}`, "citation-link");
        link.type = "button";
        if (match < 0) {link.disabled = true; link.title = "Reference is included in the audit receipt.";}
        else link.addEventListener("click", () => {const target = $(`evidence-${match}`); target.open = true; target.querySelector("summary").focus(); target.scrollIntoView({block: "nearest", behavior: "smooth"});});
      });
    }
    const metrics = append(node, "div", undefined, "proposal-metrics");
    if (proposal.agent) append(metrics, "span", `Investigator: ${proposal.agent}`);
    const elapsed = proposal.metrics?.elapsed_ms ?? proposal.elapsed_ms ?? proposal.latency_ms;
    if (Number.isFinite(elapsed)) append(metrics, "span", `${Math.round(elapsed)} ms`);
    const calls = proposal.metrics?.model_calls ?? proposal.metrics?.requests;
    if (calls != null) append(metrics, "span", `${calls} model call${calls === 1 ? "" : "s"}`);
  }
  function renderTimeline(incident) {
    const timeline = $("timeline"); timeline.replaceChildren();
    const entries = list(incident.timeline);
    if (!entries.length) {const li = append(timeline, "li"); append(li, "strong", "Intent saved"); append(li, "small", timeLabel(incident.created_at));}
    entries.forEach(event => {
      const li = append(timeline, "li");
      append(li, "strong", event.title ?? event.kind?.replaceAll("_", " ") ?? event.event ?? "Incident updated");
      if (event.detail) append(li, "small", event.kind === "investigated" ? "The proposed explanation was checked against the available records." : event.detail);
      if (event.ts ?? event.timestamp) append(li, "small", timeLabel(event.ts ?? event.timestamp));
    });
  }
  function renderDecision(incident, state) {
    const card = $("decision-card"), content = $("decision-content"), actions = $("decision-actions");
    content.replaceChildren(); actions.replaceChildren();
    card.hidden = !incident.proposal && !isResolved(incident) && !incident.outcome;
    if (card.hidden) return;
    const apply = canApply(incident, state.recorded);
    const supported = incident.proposal?.can_apply === true;
    card.classList.toggle("held", !isResolved(incident) && !supported);
    const outcome = incident.outcome;
    if (isResolved(incident)) {
      append(content, "h4", outcome?.title || "Resolved with evidence.");
      append(content, "p", outcome?.summary || outcome?.detail || outcome?.note || "The resolution is in the journal. Inspect the receipt to see what was established and what happened next.");
      if (outcome && (outcome.recovery_issued_cents != null || outcome.total_refunded_cents != null)) {
        const facts = append(content, "dl", undefined, "outcome-facts");
        if (outcome.recovery_issued_cents != null) addFact(facts, "Issued by recovery", money(outcome.recovery_issued_cents));
        if (outcome.total_refunded_cents != null) addFact(facts, "Total refunded", money(outcome.total_refunded_cents));
      }
    } else if (supported) {
      append(content, "h4", incident.proposal.apply_label || (["committed", "present"].includes(incident.proposal.verdict) ? "Record the result. Avoid a duplicate." : "Apply the supported resolution."));
      append(content, "p", incident.proposal.action_description || "Review the explanation and its sources. Applying this proposal rechecks the evidence, the current record and permission.");
      if (apply) {
        const button = append(actions, "button", state.busy === "resolve" ? "Applying resolution…" : incident.proposal.button_label || "Apply this resolution →", "button lime");
        button.type = "button"; button.disabled = !!state.busy || state.creating;
        button.addEventListener("click", () => controller.act("resolve", {proposal_id: incident.proposal.id}));
      }
    } else {
      append(content, "h4", incident.permission?.active === false ? "No new action is authorized." : "Keep the action paused. Get the missing fact.");
      const steps = list(incident.next_steps ?? incident.proposal?.next_steps);
      if (!steps.length) append(content, "p", incident.proposal?.next_probe || "The available record does not support a safe resolution. Inspect the evidence and obtain an authoritative, current result before attempting the action again.");
      steps.forEach(step => {
        if (typeof step === "string") append(content, "p", step);
        else {
          if (step.title) append(content, "p", step.title);
          if (step.detail) append(content, "p", step.detail);
          if (step.action === "probe" && !state.recorded) {
            const button = append(actions, "button", state.busy === "probe" ? "Fetching evidence…" : step.button_label || "Get the next evidence →", "button secondary");
            button.type = "button"; button.disabled = !!state.busy || state.creating;
            button.addEventListener("click", () => controller.act("probe"));
          }
        }
      });
    }
    if (state.recorded) append(content, "p", "Recorded result. This walkthrough cannot apply a resolution or perform an action.", "small muted");
  }
  $("refresh").addEventListener("click", async () => {
    const refreshed = await controller.refresh();
    if (refreshed && controller.state.selectedId && !controller.state.busy) await controller.select(controller.state.selectedId);
  });
  $("agent").addEventListener("change", event => {agentId = event.target.value; render(controller.state);});
  $("investigate").addEventListener("click", () => controller.act("investigate", {agent: agentId}));
  $("revoke").addEventListener("click", () => controller.act("revoke"));
  $("load-receipt").addEventListener("click", () => controller.receipt());
  return {render};
}

async function boot() {
  let desk;
  let wallet;
  let walletIncident = null;
  try {
    const recorded = globalThis.BELAY_RECORDED === true;
    let fixtures = null;
    if (recorded) {
      const response = await fetch("fixtures.json", {cache: "no-store"});
      if (!response.ok) throw new Error("The recorded walkthrough could not be loaded.");
      fixtures = await response.json();
    }
    const api = createApi({recorded, fixtures});
    const controller = createDeskController({api, recorded, onChange: state => {
      desk?.render(state);
      if (wallet && state.selected?.provider === "arc" && walletIncident !== state.selected.id) {
        walletIncident = state.selected.id;
        wallet.selectIncident(walletIncident);
      }
      if (wallet && state.selected?.provider === "arc") wallet.updateIncident?.(state.selected);
    }});
    desk = mountDesk(controller);
    await controller.start();
    if (!controller.state.recorded && controller.state.config?.wallet?.enabled !== false && controller.state.config?.wallet) {
      document.getElementById("wallet-section").hidden = false;
      try {
        const {mountWallet} = await import("./wallet.js");
        wallet = await mountWallet({container: document.getElementById("wallet-panel"), config: controller.state.config.wallet, onIncident: async value => {
          const id = typeof value === "string" ? value : value?.id ?? value?.incident?.id;
          await controller.refresh();
          if (id) {await controller.select(id); document.getElementById("workspace").scrollIntoView({block: "start", behavior: "smooth"});}
        }});
        if (controller.state.selected?.provider === "arc") {
          walletIncident = controller.state.selected.id;
          wallet.selectIncident(walletIncident);
          wallet.updateIncident?.(controller.state.selected);
        }
      } catch (error) {document.getElementById("wallet-panel").textContent = `The optional wallet panel could not load: ${error.message}`;}
    }
  } catch (error) {
    const banner = document.getElementById("error"); banner.hidden = false; banner.textContent = error.message;
    document.getElementById("mode-label").textContent = "Not connected";
    document.getElementById("mode-notice").textContent = "The Recovery Desk is not connected. Start the local server and reload this page.";
  }
}
if (typeof document !== "undefined") boot();
