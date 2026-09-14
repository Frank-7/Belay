(() => {
  "use strict";

  const STORAGE_KEY = "belay.payment-mission.v1";
  const AUTO_DELAY_MS = 1900;
  const CATEGORY_META = {
    purchase: { label: "Purchase", reference: "Order or payment note", required: false },
    invoice: { label: "Invoice", reference: "Invoice number", required: true },
    bill: { label: "Bill", reference: "Account or bill number", required: true },
    tax: { label: "Tax payment", reference: "Tax period or notice number", required: true },
    insurance: { label: "Insurance premium", reference: "Policy number", required: true },
    ticket: { label: "Tickets or travel", reference: "Order note", required: false },
    subscription: { label: "Subscription", reference: "Account or plan", required: false },
    transfer: { label: "Transfer", reference: "Payment note", required: false },
  };
  const POLICY_GROUPS = [
    { label: "Your approval is intact", names: ["User approved", "Plan unchanged", "Grant signature valid"] },
    { label: "Payee and reference match", names: ["Payee matches", "Reference ready", "Payee reviewed"] },
    { label: "Amount and funds match", names: ["Amount matches", "Within maximum", "Exact funds ready"] },
    { label: "USDC becomes USD", names: ["USDC source", "USD destination"] },
    { label: "Approval is active and one-time", names: ["One-time scope", "Grant active"] },
    { label: "Operation and instruction match", names: ["Operation fixed", "Signed instruction matches"] },
  ];
  const $ = (id) => document.getElementById(id);
  let config = null;
  let mission = null;
  let busy = false;
  let dirty = false;
  let autoRunning = false;
  let timer = null;
  let lastFormRevision = null;
  let investigation = null;

  class ApiError extends Error {
    constructor(message, status, current) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.current = current;
    }
  }

  function element(tag, className = "", content = null) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== null && content !== undefined) {
      node.append(document.createTextNode(String(content)));
    }
    return node;
  }

  async function api(path, body) {
    const options = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    const response = await fetch(path, options);
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError("The local service returned an unreadable response.", response.status);
    }
    if (!response.ok) {
      throw new ApiError(payload.error || "The local service could not complete this action.", response.status, payload.current);
    }
    return payload;
  }

  function remember(id) {
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Private browser modes may disable storage. The current session still works.
    }
  }

  function recalled() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function showError(message = "") {
    for (const id of ["error", "product-error"]) {
      $(id).hidden = !message || (id === "product-error" ? !mission : Boolean(mission));
      $(id).textContent = message;
    }
  }

  function usd(cents) {
    if (!Number.isInteger(cents)) return "—";
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
  }

  function usdc(units) {
    if (!Number.isInteger(units)) return "—";
    return `${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(units / 1_000_000)} USDC`;
  }

  function dollarsForInput(cents) {
    return Number.isInteger(cents) ? (cents / 100).toFixed(2) : "";
  }

  function centsFromInput(value, required) {
    const cleaned = String(value).trim();
    if (!cleaned && !required) return null;
    const parsed = Number(cleaned);
    if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 25_000) {
      throw new Error("Enter an amount from $0.01 to $25,000.00.");
    }
    return Math.round((parsed + Number.EPSILON) * 100);
  }

  function latestEvent() {
    return mission?.events?.at(-1) || null;
  }

  function isEditable() {
    return Boolean(mission && ["needs_details", "ready"].includes(mission.status));
  }

  function stopAuto() {
    autoRunning = false;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function syncPlanForm(force = false) {
    if (!mission || (!force && dirty) || lastFormRevision === mission.revision) return;
    const plan = mission.plan;
    $("plan-category").value = plan.category;
    $("plan-description").value = plan.description || "";
    $("plan-payee").value = plan.payee || "";
    $("plan-amount").value = dollarsForInput(plan.amount_usd_cents);
    $("plan-maximum").value = dollarsForInput(plan.maximum_usd_cents);
    $("plan-reference").value = plan.reference || "";
    $("plan-due-date").value = plan.due_date || "";
    lastFormRevision = mission.revision;
    dirty = false;
  }

  function progressIndex() {
    if (!mission) return -1;
    if (mission.stage === "complete") return 4;
    if (mission.stage === "review_required") {
      return mission.states?.confirmation === "integrity_failed" || mission.provider_payment?.status === "paid" ? 4 : 3;
    }
    if (["checked", "held", "signed", "dispatched", "payout_unknown", "paid", "blocked"].includes(mission.stage)) return 3;
    if (mission.stage === "authorized") return 2;
    if (["plan_ready", "needs_details"].includes(mission.stage) || ["ready", "needs_details"].includes(mission.status)) return 1;
    return 0;
  }

  function renderProgress() {
    const current = progressIndex();
    const complete = mission?.stage === "complete";
    const stopped = Boolean(mission?.terminal && !complete);
    $("progress-steps").querySelectorAll("li").forEach((item, index) => {
      item.classList.toggle("current", index === current && !complete);
      item.classList.toggle("done", index < current || (complete && index <= current));
      item.classList.toggle("failed", stopped && index === current);
      const label = item.querySelector("span").textContent;
      const state = stopped && index === current ? "stopped" : index < current || (complete && index <= current) ? "complete" : index === current ? "current" : "waiting";
      item.setAttribute("aria-label", `${label}: ${state}`);
    });
  }

  function renderStatus() {
    const event = latestEvent();
    const pulse = $("status-pulse");
    pulse.className = "status-pulse";
    if (mission?.terminal && mission.stage === "complete") pulse.classList.add("complete");
    else if (mission?.terminal || mission?.stage === "blocked") pulse.classList.add("blocked");
    else if (autoRunning || busy) pulse.classList.add("running");

    const labels = {
      analyzed: "PAYMENT PLAN",
      needs_details: "DETAILS NEEDED",
      plan_ready: "READY TO AUTHORIZE",
      authorized: "AUTHORIZED",
      checked: "CHECKS PASSED",
      held: "FUNDS RESERVED",
      signed: "INSTRUCTION LOCKED",
      dispatched: "PAYMENT SENT",
      payout_unknown: "PAYOUT NEEDS EVIDENCE",
      paid: "USD DELIVERED",
      complete: "PAYMENT COMPLETE",
      blocked: "PAYMENT STOPPED",
      review_required: "REVIEW REQUIRED",
    };
    const statusKey = mission?.status === "needs_details" ? "needs_details" : mission?.stage;
    $("status-label").textContent = labels[statusKey] || "PAYMENT MISSION";
    $("product-title").textContent = event?.title || mission?.title || "Ready for your review";
  }

  function renderConversation() {
    $("request-bubble").textContent = mission.request_text;
    $("assistant-bubble").textContent = mission.user_message;
    $("assistant-bubble").classList.toggle("thinking", autoRunning && !mission.terminal);
  }

  function markMissingFields() {
    const missing = new Set((mission.missing_fields || []).map((item) => item.field));
    if (dirty) {
      if ($("plan-payee").value.trim()) missing.delete("payee");
      else missing.add("payee");
      if ($("plan-amount").value.trim()) missing.delete("amount_usd_cents");
      else missing.add("amount_usd_cents");
      const category = CATEGORY_META[$("plan-category").value] || CATEGORY_META.purchase;
      if (category.required && !$("plan-reference").value.trim()) missing.add("reference");
      else missing.delete("reference");
    }
    const map = {
      payee: "plan-payee",
      amount_usd_cents: "plan-amount",
      reference: "plan-reference",
    };
    Object.entries(map).forEach(([field, id]) => {
      $(id).closest(".field").classList.toggle("missing", missing.has(field));
      $(id).setAttribute("aria-invalid", String(missing.has(field)));
    });
    const note = $("missing-note");
    const messages = [];
    if (missing.size) {
      const questions = [];
      if (missing.has("payee")) questions.push("Who should receive the payment?");
      if (missing.has("amount_usd_cents")) questions.push("What exact amount should be paid?");
      if (missing.has("reference")) questions.push("What payment reference should be attached?");
      messages.push(`Before authorization: ${questions.join(" ")}`);
    }
    messages.push(...(mission.plan.review_notes || []));
    if (mission.plan.due_date && mission.plan.due_date !== "Not specified") {
      messages.push(`The date “${mission.plan.due_date}” is recorded in the authorization. This demo starts payment immediately after you approve.`);
    }
    note.hidden = messages.length === 0;
    note.textContent = messages.join(" ");
  }

  function renderPlan() {
    syncPlanForm();
    const plan = mission.plan;
    const editable = isEditable();
    const selectedCategory = $("plan-category").value || plan.category;
    const category = CATEGORY_META[selectedCategory] || CATEGORY_META.purchase;
    $("category-label").textContent = `${category.label.toUpperCase()} PLAN`;
    $("reference-label").textContent = category.reference + (category.required ? " *" : "");
    $("plan-reference").required = category.required;
    $("plan-form").classList.toggle("locked", !editable);
    for (const id of ["plan-category", "plan-description", "plan-payee", "plan-amount", "plan-maximum", "plan-reference", "plan-due-date"]) {
      $(id).disabled = busy || !editable;
    }
    markMissingFields();

    const payeeChanged = dirty && $("plan-payee").value.trim() !== plan.payee;
    if (payeeChanged) {
      $("beneficiary-id").textContent = "Pending save";
      $("beneficiary-status").textContent = "A fictional ID will be resolved when you save";
    } else if (plan.payee_id) {
      $("beneficiary-id").textContent = plan.payee_id;
      $("beneficiary-status").textContent = plan.beneficiary_status === "fictional_local_fixture" ? "Fictional local identity fixture" : plan.beneficiary_status.replaceAll("_", " ");
    } else {
      $("beneficiary-id").textContent = "Unresolved";
      $("beneficiary-status").textContent = "Authorization stays blocked until a payee is saved";
    }

    const state = $("plan-state");
    if (dirty) state.textContent = "UNSAVED";
    else if (mission.stage === "review_required") state.textContent = "REVIEW NEEDED";
    else if (mission.terminal) state.textContent = mission.stage === "complete" ? "COMPLETE" : "STOPPED";
    else if (mission.grant) state.textContent = "LOCKED";
    else if (mission.can_authorize) state.textContent = "READY";
    else state.textContent = "NEEDS DETAILS";
    state.className = `state-badge${mission.terminal && mission.stage !== "complete" ? " blocked" : mission.can_authorize || mission.grant ? " active" : ""}`;

    $("save-plan").hidden = !editable;
    $("save-plan").disabled = busy;
    $("save-plan").textContent = dirty ? "Save changes" : "Plan saved";
    $("authorize-payment").hidden = !editable;
    $("authorize-payment").disabled = busy || dirty || !mission.can_authorize;
    $("resume-payment").hidden = !mission.can_advance || autoRunning;
    $("resume-payment").disabled = busy;
  }

  function renderAuthorization() {
    const card = $("authorization-card");
    card.hidden = !mission.grant;
    if (!mission.grant) return;
    const plan = mission.plan;
    const expiry = new Date(mission.grant.expires_at * 1000);
    $("authorization-summary").textContent = `${usd(plan.amount_usd_cents)} to ${plan.payee} · one payment · expires ${expiry.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    const state = $("authorization-state");
    state.textContent = mission.terminal ? "CLOSED" : "ACTIVE";
    state.className = `state-badge ${mission.terminal ? "" : "active"}`;
  }

  function currentFinding(finding = investigation) {
    return Boolean(finding && mission && mission.can_investigate
      && finding.schema_version === "belay.payment.investigation.v1"
      && finding.run_id === mission.id && finding.revision === mission.revision
      && Array.isArray(finding.checks)
      && finding.checks.every((check) => check && typeof check.label === "string" && typeof check.passed === "boolean")
      && ["paid", "unknown", "conflict"].includes(finding.verdict)
      && ((finding.operation_id === mission.operation_id
        && typeof mission.recovery_intent_digest === "string"
        && finding.intent_digest === mission.recovery_intent_digest
        && (/^sha256:[a-f0-9]{64}$/.test(finding.evidence_digest || "")
          || (finding.evidence_digest === null && finding.verdict === "unknown" && finding.can_reconcile === false)))
        // An unreadable authority can explain a manual-review block, never authorize a write.
        || (finding.verdict === "unknown" && finding.can_reconcile === false
          && finding.operation_id === null && finding.intent_digest === null && finding.evidence_digest === null)));
  }

  function canReconcile() {
    return currentFinding() && investigation.verdict === "paid"
      && investigation.can_reconcile === true
      && Array.isArray(investigation.checks) && investigation.checks.length > 0
      && investigation.checks.every((check) => check.passed === true);
  }

  function renderRecovery() {
    if (!currentFinding()) investigation = null;
    $("recovery-card").hidden = !mission.can_investigate;
    $("investigate-payment").disabled = busy || !mission.can_investigate;
    $("investigate-payment").textContent = investigation ? "Check evidence again" : "Investigate evidence";
    $("reconcile-payment").hidden = !canReconcile();
    $("reconcile-payment").disabled = busy || !canReconcile();
    $("recovery-finding").hidden = !investigation;
    if (!investigation) return;
    const labels = { paid: "Payout evidence matches", unknown: "Evidence is incomplete", conflict: "Evidence conflicts" };
    $("recovery-verdict").textContent = labels[investigation.verdict];
    $("recovery-summary").textContent = investigation.summary;
    $("recovery-checks").replaceChildren(...(investigation.checks || []).map((check) => {
      const item = element("li", check.passed === true ? "passed" : "failed");
      item.append(element("b", "", check.passed === true ? "Pass" : "Hold"), element("span", "", check.label));
      return item;
    }));
    $("recovery-evidence").textContent = pretty({
      mission_id: investigation.run_id, revision: investigation.revision,
      operation_id: investigation.operation_id, intent_digest: investigation.intent_digest,
      evidence_digest: investigation.evidence_digest,
      observations: investigation.observations, citations: investigation.citations,
    });
  }

  function renderReceipt() {
    const card = $("receipt-card");
    const receipt = mission.receipt;
    card.hidden = !receipt;
    if (!receipt) return;
    $("receipt-title").textContent = receipt.confirmation;
    $("receipt-payee").textContent = receipt.payee;
    $("receipt-amount").textContent = usd(receipt.amount_usd_cents);
    $("receipt-reference").textContent = receipt.reference || "No reference needed";
    $("receipt-id").textContent = receipt.receipt_id;
    $("receipt-limit").textContent = usd(mission.grant?.maximum_usd_cents ?? mission.plan.maximum_usd_cents);
    $("receipt-date").textContent = mission.grant?.due_date || mission.plan.due_date || "Not specified";
    $("receipt-operation").textContent = receipt.operation_id || mission.operation_id;
    $("receipt-provider").textContent = receipt.payment?.provider_reference || mission.provider_payment?.provider_reference || "Not recorded";
    $("receipt-attempts").textContent = String(receipt.payment?.attempt_count ?? mission.provider_payment?.attempt_count ?? 0);
    $("receipt-authorization").textContent = receipt.authorization_digest || mission.grant?.signature || "Not recorded";
    $("receipt-confirmation").textContent = `Belay linked the request, exact authorization, one operation, and one simulated ${usd(receipt.payment?.amount_usd_cents ?? receipt.amount_usd_cents)} USD payout.`;
    const external = receipt.domain_outcome;
    $("receipt-scope").textContent = external
      ? `${external.label} is ${String(external.status).replaceAll("_", " ")}. ${external.scope}`
      : receipt.scope;
  }

  function renderBackendNow() {
    const event = latestEvent();
    $("event-number").textContent = String((event?.number || 0) + 1).padStart(2, "0");
    $("backend-actor").textContent = (event?.backend?.actor || "Belay").toUpperCase();
    $("backend-action").textContent = event?.backend?.action || event?.title || "Prepare the payment";
    $("backend-explanation").textContent = event?.backend?.control || "Belay turns the request into a plan without moving money.";
    $("backend-proof").textContent = event?.backend?.proof || "No proof recorded yet";
    $("backend-retry").textContent = event?.backend?.safe_retry || "No money moved";
    $("sync-label").textContent = mission.stage === "complete" ? "Final linked state" : mission.terminal ? "Final stopped state" : "Same live event";
  }

  function simpleChecks() {
    const policy = mission.policy_decision;
    const byName = new Map((policy?.checks || []).map((item) => [item.name, item.passed]));
    const groups = POLICY_GROUPS.map((group) => {
      const represented = group.names.every((name) => byName.has(name));
      const passed = Boolean(policy && represented && group.names.every((name) => byName.get(name) === true));
      return {
        name: group.label,
        detail: `${group.names.length} backend ${group.names.length === 1 ? "check" : "checks"}`,
        status: !policy ? "waiting" : passed ? "passed" : "failed",
        passed,
      };
    });
    if (policy?.allowed === false && groups.every((group) => group.passed)) {
      groups.at(-1).passed = false;
      groups.at(-1).status = "failed";
      groups.at(-1).detail = "Backend decision rejected";
    }
    return groups;
  }

  function renderChecks() {
    const checks = simpleChecks();
    $("check-list").replaceChildren(...checks.map((check) => {
      const item = element("div", `check-item ${check.status}`);
      const copy = element("span");
      copy.append(element("strong", "", check.name), element("small", "", check.detail));
      item.append(element("i", "", check.status === "passed" ? "✓" : check.status === "failed" ? "!" : "○"), copy);
      return item;
    }));
    const backendChecks = mission.policy_decision?.checks || [];
    const passed = backendChecks.filter((item) => item.passed).length;
    const allowed = mission.policy_decision?.allowed === true && passed === 15 && backendChecks.length === 15;
    $("check-score").textContent = mission.policy_decision
      ? `${passed} of ${backendChecks.length} passed${mission.policy_decision.allowed ? "" : " · stopped"}`
      : mission.grant ? "15 checks about to run" : "Runs after approval";
    $("check-score").classList.toggle("complete", allowed);
  }

  function moneyChangeText(event) {
    const before = event?.money_before;
    const after = event?.money_after;
    if (!before || !after) return "No money moved";
    if (after.payment_hold_usdc_units > before.payment_hold_usdc_units) return `${usdc(after.payment_hold_usdc_units - before.payment_hold_usdc_units)} reserved`;
    if (after.provider_in_transit_usdc_units > before.provider_in_transit_usdc_units) return `${usdc(after.provider_in_transit_usdc_units - before.provider_in_transit_usdc_units)} sent once`;
    if (after.payee_received_usd_cents > before.payee_received_usd_cents) return `${usd(after.payee_received_usd_cents - before.payee_received_usd_cents)} delivered`;
    const returned = before.payment_hold_usdc_units - after.payment_hold_usdc_units;
    if (returned > 0 && after.customer_available_usdc_units > before.customer_available_usdc_units) {
      return `${usdc(returned)} returned · no payout`;
    }
    if (event?.stage === "complete" && after.payee_received_usd_cents > 0) {
      return `No new movement · ${usd(after.payee_received_usd_cents)} paid once`;
    }
    return "No money moved";
  }

  function renderMoney() {
    const money = mission.money;
    const event = latestEvent();
    $("wallet-balance").textContent = usdc(money.customer_available_usdc_units);
    $("money-customer-value").textContent = usdc(money.customer_available_usdc_units);
    $("money-hold-value").textContent = usdc(money.payment_hold_usdc_units);
    $("money-provider-value").textContent = usdc(money.provider_in_transit_usdc_units);
    $("money-payee-value").textContent = usd(money.payee_received_usd_cents);
    $("money-payee-label").textContent = mission.plan.payee || "waiting";
    $("money-effect").textContent = moneyChangeText(event);

    const order = ["money-customer", "money-hold", "money-provider", "money-payee"];
    const active = money.payee_received_usd_cents > 0 ? 3 : money.provider_in_transit_usdc_units > 0 ? 2 : money.payment_hold_usdc_units > 0 ? 1 : 0;
    order.forEach((id, index) => {
      const node = $(id);
      node.classList.toggle("active", index === active && mission.stage !== "complete");
      node.classList.toggle("done", index < active || (mission.stage === "complete" && index <= active));
      const before = event?.money_before;
      const after = event?.money_after;
      const fields = ["customer_available_usdc_units", "payment_hold_usdc_units", "provider_in_transit_usdc_units", "payee_received_usd_cents"];
      node.classList.toggle("changed", Boolean(before && after && before[fields[index]] !== after[fields[index]]));
    });
  }

  function proofRecords() {
    return [
      { label: "Original request digest", value: mission.request_digest, present: Boolean(mission.request_digest) },
      { label: "Versioned payment plan", value: `plan revision ${mission.plan_revision}`, present: Number.isInteger(mission.plan_revision) },
      { label: "Signed user authorization", value: mission.grant?.signature, present: Boolean(mission.grant) },
      { label: "Single payment operation", value: mission.provider_payment?.provider_reference || mission.operation_id, present: Boolean(mission.provider_payment) },
      { label: "Linked final receipt", value: mission.receipt?.receipt_id, present: Boolean(mission.receipt) },
    ];
  }

  function renderProofs() {
    const records = proofRecords();
    $("proof-list").replaceChildren(...records.map((record) => {
      const item = element("article", `proof-item${record.present ? " present" : ""}`);
      const copy = element("div");
      copy.append(element("strong", "", record.label), element("span", "", record.present ? record.value : "Waiting for this step"));
      item.append(element("i", "", record.present ? "✓" : "○"), copy, element("b", "", record.present ? "WRITTEN" : "WAITING"));
      return item;
    }));
    const present = records.filter((record) => record.present).length;
    $("proof-score").textContent = `${present} of ${records.length}`;
    $("proof-score").classList.toggle("complete", present === records.length);
  }

  function pretty(value) {
    return JSON.stringify(value ?? {}, null, 2);
  }

  function renderAudit() {
    const event = latestEvent();
    $("mission-id").textContent = mission.id;
    $("operation-id").textContent = mission.operation_id;
    $("provider-attempts").textContent = String(mission.provider_payment?.attempt_count || 0);
    $("safe-retry").textContent = event?.backend?.safe_retry || "No money moved";
    $("state-payload").textContent = pretty({
      revision: mission.revision,
      plan_revision: mission.plan_revision,
      request_digest: mission.request_digest,
      status: mission.status,
      states: mission.states,
      money: mission.money,
      policy_decision: mission.policy_decision,
    });
    $("request-payload").textContent = pretty(event?.backend?.request);
    $("response-payload").textContent = pretty(event?.backend?.response);

    if (!mission.ledger?.length) {
      $("ledger-list").replaceChildren(element("p", "empty", "No value-moving entry yet."));
    } else {
      $("ledger-list").replaceChildren(...mission.ledger.map((entry) => {
        const item = element("article");
        item.append(
          element("strong", "", `${entry.account_from} → ${entry.account_to}`),
          element("span", "", entry.asset === "USDC_TO_USD_1_TO_1_DEMO" ? `${usdc(entry.units)} → ${usd(entry.units / 10_000)}` : usdc(entry.units)),
          element("code", "", entry.idempotency_key),
        );
        return item;
      }));
    }

    $("event-list").replaceChildren(...(mission.events || []).map((historyEvent) => {
      const item = element("li");
      item.append(element("b", "", String(historyEvent.number + 1).padStart(2, "0")), element("span", "", historyEvent.title));
      return item;
    }));
  }

  function render() {
    if (mission && (!mission.can_advance || mission.terminal)) stopAuto();
    $("mission-form").setAttribute("aria-busy", String(busy));
    $("request-input").disabled = busy || Boolean(mission);
    $("analyze").disabled = busy || Boolean(mission);
    $("simulate-lost-reply").disabled = busy || Boolean(mission);
    $("new-mission").disabled = busy;
    $("product").hidden = !mission;
    document.querySelectorAll(".example-chip").forEach((button) => { button.disabled = busy || Boolean(mission); });
    if (!mission) return;
    $("product").setAttribute("aria-busy", String(busy));
    renderStatus();
    renderProgress();
    renderConversation();
    renderPlan();
    renderAuthorization();
    renderRecovery();
    renderReceipt();
    renderBackendNow();
    renderChecks();
    renderMoney();
    renderProofs();
    renderAudit();
  }

  function scheduleAdvance() {
    if (!autoRunning || busy || !mission?.can_advance || mission.terminal) {
      if (mission && (!mission.can_advance || mission.terminal)) stopAuto();
      render();
      return;
    }
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => advanceOne(true), AUTO_DELAY_MS);
  }

  async function recoverConflict(error) {
    investigation = null;
    if (error.current && error.current.id === mission?.id) {
      mission = error.current;
      return true;
    }
    if (error.status === 409 && mission?.id) {
      try {
        mission = await api(`/api/missions/${encodeURIComponent(mission.id)}`);
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }

  async function advanceOne(automatic) {
    if (busy || !mission?.can_advance || mission.terminal) return;
    busy = true;
    showError();
    render();
    try {
      mission = await api(`/api/missions/${encodeURIComponent(mission.id)}/advance`, { expected_revision: mission.revision });
      remember(mission.id);
    } catch (error) {
      stopAuto();
      const recovered = await recoverConflict(error);
      showError(recovered ? `${error.message} The current mission was reloaded; review it before continuing.` : `${error.message} Belay paused without repeating the payment.`);
    } finally {
      busy = false;
      render();
    }
    if (mission?.terminal && mission.receipt && automatic) $("receipt-card").focus({ preventScroll: true });
    scheduleAdvance();
  }

  function planFields() {
    const fields = {
      category: $("plan-category").value,
      description: $("plan-description").value.trim(),
      payee: $("plan-payee").value.trim(),
      amount_usd_cents: centsFromInput($("plan-amount").value, true),
      maximum_usd_cents: centsFromInput($("plan-maximum").value, false),
      reference: $("plan-reference").value.trim(),
      due_date: $("plan-due-date").value.trim() || "Not specified",
    };
    if (!fields.payee) throw new Error("Enter who should receive the payment.");
    const category = CATEGORY_META[fields.category] || CATEGORY_META.purchase;
    if (category.required && !fields.reference) {
      throw new Error(`Enter the ${category.reference.toLowerCase()}.`);
    }
    if (fields.maximum_usd_cents !== null && fields.amount_usd_cents > fields.maximum_usd_cents) {
      throw new Error("The exact amount cannot be higher than your maximum.");
    }
    return fields;
  }

  $("mission-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || mission) return;
    const request = $("request-input").value.trim();
    if (!$("mission-form").reportValidity()) return;
    busy = true;
    showError();
    render();
    try {
      mission = await api("/api/missions/analyze", {
        request, demo_outcome: $("simulate-lost-reply").checked ? "payout_reply_lost" : "success",
      });
      investigation = null;
      remember(mission.id);
      lastFormRevision = null;
      dirty = false;
      setMobileView("customer");
      render();
      $("product").scrollIntoView({ behavior: "smooth", block: "start" });
      const firstMissing = mission.missing_fields?.[0]?.field;
      const focusMap = { payee: "plan-payee", amount_usd_cents: "plan-amount", reference: "plan-reference" };
      setTimeout(() => $(focusMap[firstMissing] || "authorize-payment").focus(), 350);
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      render();
    }
  });

  for (const id of ["plan-category", "plan-description", "plan-payee", "plan-amount", "plan-maximum", "plan-reference", "plan-due-date"]) {
    $(id).addEventListener(id === "plan-category" ? "change" : "input", () => {
      if (!isEditable()) return;
      dirty = true;
      render();
    });
  }

  $("plan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !isEditable()) return;
    if (!$("plan-form").reportValidity()) return;
    let fields;
    try {
      fields = planFields();
    } catch (error) {
      showError(error.message);
      return;
    }
    busy = true;
    showError();
    render();
    try {
      mission = await api(`/api/missions/${encodeURIComponent(mission.id)}/details`, { expected_revision: mission.revision, fields });
      lastFormRevision = null;
      dirty = false;
      syncPlanForm(true);
    } catch (error) {
      if (await recoverConflict(error)) {
        dirty = false;
        lastFormRevision = null;
        syncPlanForm(true);
      }
      showError(error.message);
    } finally {
      busy = false;
      render();
    }
    if (mission?.can_authorize) $("authorize-payment").focus();
  });

  $("authorize-payment").addEventListener("click", async () => {
    if (busy || dirty || !mission?.can_authorize) return;
    busy = true;
    showError();
    render();
    try {
      mission = await api(`/api/missions/${encodeURIComponent(mission.id)}/authorize`, { expected_revision: mission.revision });
      remember(mission.id);
      lastFormRevision = null;
      syncPlanForm(true);
      autoRunning = true;
    } catch (error) {
      await recoverConflict(error);
      showError(error.message);
    } finally {
      busy = false;
      render();
    }
    scheduleAdvance();
  });

  $("resume-payment").addEventListener("click", () => {
    if (busy || !mission?.can_advance) return;
    showError();
    autoRunning = true;
    render();
    scheduleAdvance();
  });

  $("investigate-payment").addEventListener("click", async () => {
    if (busy || !mission?.can_investigate) return;
    stopAuto();
    investigation = null;
    busy = true;
    showError();
    render();
    const expected = { id: mission.id, revision: mission.revision };
    try {
      const finding = await api(`/api/missions/${encodeURIComponent(expected.id)}/investigate`, { expected_revision: expected.revision });
      if (mission?.id !== expected.id || mission.revision !== expected.revision || !currentFinding(finding)) {
        throw new Error("The evidence does not match the current payment. Investigate again before reconciling.");
      }
      investigation = finding;
    } catch (error) {
      await recoverConflict(error);
      showError(`${error.message} No payment was repeated or reconciled.`);
    } finally {
      busy = false;
      render();
    }
  });

  $("reconcile-payment").addEventListener("click", async () => {
    if (busy || !canReconcile()) return;
    stopAuto();
    busy = true;
    showError();
    render();
    const expected = { id: mission.id, revision: mission.revision, evidence: investigation.evidence_digest };
    investigation = null;
    try {
      mission = await api(`/api/missions/${encodeURIComponent(expected.id)}/reconcile`, {
        expected_revision: expected.revision, evidence_digest: expected.evidence,
      });
      remember(mission.id);
      autoRunning = mission.can_advance && !mission.can_investigate;
    } catch (error) {
      await recoverConflict(error);
      showError(`${error.message} Investigate again before continuing; Belay will not repeat the payout.`);
    } finally {
      busy = false;
      render();
    }
    scheduleAdvance();
  });

  $("new-mission").addEventListener("click", () => {
    if (busy) return;
    stopAuto();
    mission = null;
    investigation = null;
    dirty = false;
    lastFormRevision = null;
    remember(null);
    $("request-input").value = "";
    $("simulate-lost-reply").checked = false;
    $("technical-audit").open = false;
    setMobileView("customer");
    showError();
    render();
    $("mission").scrollIntoView({ behavior: "smooth", block: "start" });
    $("request-input").focus({ preventScroll: true });
  });

  function setMobileView(view, focusTab = false) {
    const customerSelected = view === "customer";
    $("workspace").dataset.mobileView = view;
    $("view-customer").setAttribute("aria-selected", String(customerSelected));
    $("view-backend").setAttribute("aria-selected", String(!customerSelected));
    $("view-customer").tabIndex = customerSelected ? 0 : -1;
    $("view-backend").tabIndex = customerSelected ? -1 : 0;
    const mobile = window.matchMedia("(max-width: 960px)").matches;
    if (mobile) {
      $("customer-panel").setAttribute("role", "tabpanel");
      $("backend-panel").setAttribute("role", "tabpanel");
      $("customer-panel").setAttribute("aria-labelledby", "view-customer");
      $("backend-panel").setAttribute("aria-labelledby", "view-backend");
      $("customer-panel").setAttribute("aria-hidden", String(!customerSelected));
      $("backend-panel").setAttribute("aria-hidden", String(customerSelected));
    } else {
      $("customer-panel").removeAttribute("role");
      $("backend-panel").removeAttribute("role");
      $("customer-panel").setAttribute("aria-labelledby", "customer-title");
      $("backend-panel").setAttribute("aria-labelledby", "backend-title");
      $("customer-panel").removeAttribute("aria-hidden");
      $("backend-panel").removeAttribute("aria-hidden");
    }
    if (focusTab) $(customerSelected ? "view-customer" : "view-backend").focus();
  }
  $("view-customer").addEventListener("click", () => setMobileView("customer"));
  $("view-backend").addEventListener("click", () => setMobileView("backend"));
  for (const id of ["view-customer", "view-backend"]) {
    $(id).addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let view;
      if (event.key === "Home") view = "customer";
      else if (event.key === "End") view = "backend";
      else view = $("workspace").dataset.mobileView === "customer" ? "backend" : "customer";
      setMobileView(view, true);
    });
  }
  window.addEventListener("resize", () => setMobileView($("workspace").dataset.mobileView));

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && autoRunning) {
      stopAuto();
      render();
    }
  });

  async function initialize() {
    busy = true;
    render();
    try {
      config = await api("/api/mission/config");
      $("example-list").replaceChildren(...(config.examples || []).map((example) => {
        const button = element("button", "example-chip", example);
        button.type = "button";
        button.title = example;
        button.addEventListener("click", () => {
          $("request-input").value = example;
          $("request-input").focus();
        });
        return button;
      }));

      const saved = recalled();
      if (saved && /^[a-f0-9]{32}$/.test(saved)) {
        try {
          mission = await api(`/api/missions/${encodeURIComponent(saved)}`);
          $("request-input").value = mission.request_text;
          $("simulate-lost-reply").checked = mission.demo_outcome === "payout_reply_lost";
          lastFormRevision = null;
          dirty = false;
          setMobileView("customer");
        } catch {
          remember(null);
          showError("The saved demo mission is unavailable. Start a new request.");
        }
      }
    } catch (error) {
      showError(`Could not connect to the local Belay service: ${error.message}`);
    } finally {
      busy = false;
      setMobileView($("workspace").dataset.mobileView || "customer");
      render();
    }
  }

  initialize();
})();
