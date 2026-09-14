(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = "belay-protected-purchase-v04-run";
  const USDC_SCALE = 1_000_000;
  const CORE_POLICY_GROUPS = [
    ["Consent & authority", ["customer_approved", "demo_grant_marker", "grant_not_before", "grant_expiry"]],
    ["Purchase terms", ["quantity", "maximum_total", "grant_unit_consistency", "event", "date", "venue", "offer_arithmetic", "seat_count", "adjacent_seats"]],
    ["Merchant identity", ["seller", "payout_beneficiary"]],
    ["Settlement", ["source_asset", "source_amount", "source_within_grant", "merchant_net", "destination_asset", "demo_fee"]],
    ["Quote validity", ["quote_not_before", "quote_expiry"]],
  ];
  const CHAPTERS = ["authorize", "propose", "control", "settle", "verify", "recover"];

  let run = null;
  let config = null;
  let busy = false;
  let playing = false;
  let timer = null;
  let followLatest = true;
  let selectedEventId = null;
  let investigation = null;

  const usdc = (units, digits = 0) => `${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: Math.max(digits, 2),
  }).format(Number(units || 0) / USDC_SCALE)} USDC`;

  const usd = (cents) => new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: Number(cents || 0) % 100 ? 2 : 0,
  }).format(Number(cents || 0) / 100);

  const human = (value) => String(value ?? "not_started")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  const accountName = (value) => ({
    customer_available: "Customer available",
    order_hold: "Exact order hold",
    provider_in_transit: "Conversion provider",
    merchant_received: "Merchant received",
    protection_reserve: "Protection reserve",
  })[value] || human(value || "System");

  const safeText = (value) => {
    if (typeof value === "string") return value;
    if (value === undefined) return "—";
    return JSON.stringify(value);
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showError(message = "") {
    $("error").textContent = message;
    $("error").hidden = !message;
  }

  function remember(id) {
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Browser persistence is optional.
    }
  }

  function recalled() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  async function api(path, body) {
    const options = body === undefined
      ? { cache: "no-store" }
      : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) {
      if (result.current) {
        run = result.current;
        followLatest = true;
        selectedEventId = null;
        render();
      }
      throw new Error(result.error || `Local request failed (${response.status}).`);
    }
    return result;
  }

  function events() {
    return run?.events || [];
  }

  function latestEvent() {
    return events().at(-1) || null;
  }

  function selectedEvent() {
    if (!run) return null;
    if (followLatest) return latestEvent();
    return events().find((event) => event.id === selectedEventId) || latestEvent();
  }

  function viewStep() {
    return selectedEvent()?.step ?? run?.step ?? 0;
  }

  function stopPlayback() {
    playing = false;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function isUnknown() {
    return run?.payout_state === "unknown";
  }

  function requiresManualAction() {
    return isUnknown() || Boolean(run?.manual_review);
  }

  function needsPayoutInvestigation() {
    return isUnknown() && run?.step === 8 && run?.stage !== "dispatch_unknown";
  }

  function currentInvestigation() {
    return investigation?.run_id === run?.id && investigation?.revision === run?.revision
      ? investigation : null;
  }

  function canReconcilePayout() {
    const finding = currentInvestigation();
    return finding?.verdict === "paid" && finding?.can_reconcile === true;
  }

  function chapterFor(event) {
    const stage = event?.stage || run?.stage;
    if (["mission_authorized", "historical_fixture_loaded", "grant_expired"].includes(stage)) return "authorize";
    if (["offer_found", "checkout_bound"].includes(stage)) return "propose";
    if (["policy_blocked", "admitted", "intent_signed", "terms_rejected"].includes(stage)) return "control";
    if (["cancelled", "dispatch_unknown", "usdc_dispatched", "converted", "payout_submitted", "payout_unknown", "merchant_paid", "payout_reconciled", "order_confirmed"].includes(stage)) return "settle";
    if (["delivery_check", "non_delivery", "review_required", "delivered", "agent_error_detected"].includes(stage)) return "verify";
    return "recover";
  }

  function updateButtons() {
    const actionable = run && !run.terminal && run.can_advance;
    if (!actionable || requiresManualAction()) stopPlayback();
    $("start").disabled = busy || Boolean(run);
    $("scenario").disabled = busy || Boolean(run);
    $("play").disabled = busy || !actionable || requiresManualAction();
    $("next").disabled = busy || !actionable || playing || (needsPayoutInvestigation() && !canReconcilePayout());
    $("investigate").disabled = busy || !needsPayoutInvestigation();
    $("reset").disabled = busy || !run;
    $("play").textContent = playing ? "Pause" : "Auto play";
    $("play").setAttribute("aria-pressed", String(playing));
    $("next").replaceChildren(
      document.createTextNode(run?.stage === "dispatch_unknown" ? "Reconcile original dispatch " : isUnknown() ? "Reconcile paid operation " : "Next event "),
      element("span", "", "→"),
    );
    $("next").lastElementChild.setAttribute("aria-hidden", "true");
  }

  function renderProgress() {
    const current = run?.step || 0;
    const maximum = run?.max_step || 13;
    const percent = run?.terminal ? 100 : Math.min(100, Math.round((current / maximum) * 100));
    $("progress").setAttribute("aria-valuemax", String(maximum));
    $("progress").setAttribute("aria-valuenow", String(current));
    $("progress").setAttribute("aria-valuetext", run ? `Step ${current} of ${maximum}: ${run.title}` : "Ready");
    $("progress").querySelector("span").style.width = `${percent}%`;
    $("step-count").textContent = run ? `EVENT ${String(current).padStart(2, "0")} OF ${String(maximum).padStart(2, "0")}` : "READY";
    $("current-stage").textContent = run?.title || "Authorize the mission to begin";
    $("stage-dot").dataset.kind = run?.outcome?.kind || "idle";

    const active = CHAPTERS.indexOf(chapterFor(latestEvent()));
    $("chapter-rail").querySelectorAll("li").forEach((item, index) => {
      item.classList.toggle("active", Boolean(run) && index === active);
      item.classList.toggle("complete", Boolean(run) && index < active);
    });
  }

  function renderScenario() {
    if (!config) return;
    const scenario = config.scenarios.find((item) => item.id === $("scenario").value);
    $("scenario-category").textContent = scenario?.category || "Scenario";
    $("scenario-trigger").textContent = scenario?.trigger || "Choose a scenario to inspect.";
    $("scenario-description").textContent = scenario?.description || "Select a scenario to test Belay's controls.";
    $("scenario-guarantee").textContent = scenario?.guarantee || "The run will show its terminal guarantee.";
  }

  function renderTrace() {
    const allEvents = events();
    const latest = latestEvent();
    if (followLatest || !allEvents.some((event) => event.id === selectedEventId)) {
      selectedEventId = latest?.id || null;
    }

    const selected = selectedEventId;
    const rows = allEvents.map((event) => {
      const item = element("li");
      const button = element("button");
      button.type = "button";
      button.dataset.eventId = event.id;
      button.classList.toggle("current", event.id === latest?.id);
      button.classList.toggle("inspected", event.id === selected);
      button.setAttribute("aria-label", `Inspect step ${event.step}: ${event.title}`);
      const number = element("b", "", String(event.step).padStart(2, "0"));
      const copy = element("div");
      copy.append(
        element("strong", "", event.title),
        element("span", "", `${event.actor} · ${event.method}`),
      );
      button.append(number, copy);
      button.addEventListener("click", () => {
        followLatest = event.id === latestEvent()?.id;
        selectedEventId = event.id;
        render();
        $("backend-event-card").focus();
      });
      item.append(button);
      return item;
    });
    $("trace-list").replaceChildren(...rows);
    $("event-count").textContent = `${allEvents.length} ${allEvents.length === 1 ? "event" : "events"}`;

    const priorValue = $("event-select").value;
    $("event-select").replaceChildren(...allEvents.map((event) => {
      const option = element("option", "", `${String(event.step).padStart(2, "0")} · ${event.title}`);
      option.value = event.id;
      return option;
    }));
    $("event-select").value = selected || priorValue;
    $("return-live").hidden = followLatest || !run;

    requestAnimationFrame(() => {
      const selectedButton = $("trace-list").querySelector("button.inspected");
      if (selectedButton) {
        const target = Math.max(0, selectedButton.offsetTop - ($("trace-list").clientHeight / 2));
        $("trace-list").scrollTop = target;
      }
    });
  }

  function fallbackTechnical(event) {
    return {
      layer_id: "orchestrator",
      layer: human(event?.stage || "orchestration"),
      control: event?.explanation || "Belay records this transition before the next component can act.",
      proof: "Versioned event record",
      money_effect: "See the value map for the current state.",
      retry_rule: "Money-moving retries preserve the original identity.",
    };
  }

  function renderLens() {
    const event = selectedEvent();
    const technical = event?.technical || fallbackTechnical(event);
    $("lens-step").textContent = event ? String(event.step).padStart(2, "0") : "00";
    $("lens-mode").textContent = followLatest ? "LIVE TIMELINE" : "INSPECTING PAST EVENT";
    $("lens-title").textContent = event?.title || "The customer grants one bounded mission";
    $("lens-explanation").textContent = event?.explanation || "Start the run to see one customer action become a controlled backend transaction.";
    $("customer-now").textContent = event?.user_message || "No purchase has started.";
    $("backend-now").textContent = event ? `${technical.control} Proof: ${technical.proof}.` : "No infrastructure action yet.";
  }

  function accountValue(accounts, name, fallback) {
    return accounts?.[name]?.units ?? fallback;
  }

  function formatAccountAmount(asset, units) {
    return asset === "USD_CENTS" ? `${usd(units)} USD` : usdc(units);
  }

  function renderMoney() {
    const event = selectedEvent();
    const accounts = event?.accounts_after;
    const provider = event?.provider_after;
    const buyer = accountValue(accounts, "customer_available", run?.buyer?.available_usdc_units ?? 300 * USDC_SCALE);
    const held = accountValue(accounts, "order_hold", run?.buyer?.held_usdc_units ?? 0);
    const transit = accountValue(accounts, "provider_in_transit", run?.settlement?.provider_in_transit_usdc_units ?? 0);
    const merchant = accountValue(accounts, "merchant_received", run?.settlement?.merchant_received_usd_cents ?? 0);
    const observed = event?.provider_observation?.payout_state === "paid"
      ? Number(event.provider_observation.net_usd_cents || provider?.net_usd_cents || 20_000)
      : 0;
    const unknown = event?.knowledge?.belay === "unknown";
    const protection = event?.protection_after || run?.protection || {
      reserve_cash_usdc_units: 1_000 * USDC_SCALE,
      available_usdc_units: 1_000 * USDC_SCALE,
      committed_usdc_units: 0,
      pending_usdc_units: 0,
      paid_usdc_units: 0,
    };

    $("buyer-balance").textContent = usdc(buyer);
    $("customer-wallet").textContent = usdc(buyer);
    $("held-balance").textContent = usdc(held);
    $("provider-balance").textContent = unknown
      ? "Unreconciled"
      : transit ? usdc(transit) : provider?.conversion_state === "converted" ? "Converted" : "0 USDC";
    $("provider-note").textContent = unknown
      ? `Belay book: ${usdc(transit)} in transit`
      : provider?.conversion_state === "converted" ? "Cleared into USD" : "Awaiting dispatch";
    $("merchant-balance").textContent = unknown ? `${usd(observed)} observed` : `${usd(merchant)} USD`;
    $("merchant-note").textContent = unknown ? "Provider truth · not booked yet" : merchant ? "Payout confirmed" : "Merchant payout";
    $("reserve-cash").textContent = usdc(protection.reserve_cash_usdc_units);
    $("reserve-summary").textContent = `${usdc(protection.available_usdc_units).replace(" USDC", "")} available · ${usdc(protection.committed_usdc_units).replace(" USDC", "")} committed · ${usdc(protection.pending_usdc_units).replace(" USDC", "")} pending · ${usdc(protection.paid_usdc_units).replace(" USDC", "")} paid`;

    const changedAccounts = new Set((event?.balance_changes || []).map((change) => change.account));
    const nodeMap = {
      "buyer-node": [buyer, "customer_available"],
      "hold-node": [held, "order_hold"],
      "provider-node": [transit, "provider_in_transit"],
      "merchant-node": [merchant || observed, "merchant_received"],
    };
    Object.entries(nodeMap).forEach(([id, [amount, account]]) => {
      $(id).classList.toggle("has-value", Number(amount) > 0);
      $(id).classList.toggle("changed", changedAccounts.has(account));
      $(id).classList.toggle("uncertain", unknown && ["provider-node", "merchant-node"].includes(id));
    });
    const changes = event?.balance_changes || [];
    $("money-change").textContent = unknown
      ? `ONE PAYOUT, TWO VIEWS · Belay book: ${usdc(transit)} in transit · Provider: ${usd(observed)} paid`
      : changes.length
      ? changes.slice(0, 2).map((change) => `${accountName(change.account)} ${formatAccountAmount(change.asset, change.before_units)} → ${formatAccountAmount(change.asset, change.after_units)}`).join(" · ")
      : event?.technical?.money_effect || "No value movement";
  }

  function renderConversation() {
    const allEvents = events();
    const selectedIndex = Math.max(0, allEvents.findIndex((event) => event.id === selectedEvent()?.id));
    const visibleEvents = run ? allEvents.slice(0, selectedIndex + 1).slice(-4) : [];
    const user = element("div", "message user-message");
    user.append(
      document.createTextNode("Find two adjacent tickets for The Midnight Signals on October 24. Stay under "),
      element("strong", "", "300 USDC total."),
    );
    const messages = visibleEvents.map((event, index) => {
      const message = element("div", `message agent-message ${index === visibleEvents.length - 1 ? "current" : "older"}`);
      message.append(
        element("span", "message-step", `BELAY · STEP ${String(event.step).padStart(2, "0")}`),
        document.createTextNode(event.user_message || event.title),
      );
      return message;
    });
    if (!messages.length) {
      const initial = element("div", "message agent-message", "Choose a scenario and authorize the mission. I will explain each action in plain language.");
      initial.id = "agent-message";
      messages.push(initial);
    }
    $("customer-conversation").replaceChildren(user, ...messages);
    requestAnimationFrame(() => {
      $("customer-conversation").scrollTop = $("customer-conversation").scrollHeight;
    });
  }

  function renderOffer() {
    const offer = run?.offer;
    const visible = Boolean(offer) && (viewStep() >= 1 || run?.entry_mode === "injected_historical_fixture");
    $("offer-card").hidden = !visible;
    if (!visible) return;
    $("offer-quantity").textContent = `${offer.quantity} adjacent ticket${offer.quantity === 1 ? "" : "s"}`;
    $("offer-price").textContent = `${usd(offer.total_usd_cents)} USD`;
    $("offer-seats").textContent = offer.seats.join(" · ");
    const decision = viewStep() >= 3 ? run.policy_decision : null;
    const violation = decision?.allowed === false;
    $("offer-status").textContent = !decision ? "Agent proposal" : decision.allowed ? "23 checks passed" : "Does not match grant";
    $("offer-status").classList.toggle("danger", violation);
    $("offer-card").classList.toggle("violation", violation);
  }

  function renderOutcome() {
    const event = selectedEvent();
    const outcome = event?.outcome || run?.outcome || {
      kind: "active", headline: "Mission not started", detail: "No money has moved.",
    };
    $("outcome").className = `outcome ${outcome.kind || "active"}`;
    $("outcome-headline").textContent = outcome.headline || "Mission in progress";
    $("outcome-detail").textContent = outcome.detail || "The protected transaction is still active.";
    const icons = { success: "✓", remedied: "↺", blocked: "×", warning: "!", review: "?", safe: "✓", active: "○" };
    $("outcome").querySelector(".outcome-icon").textContent = icons[outcome.kind] || "○";
  }

  function renderTickets() {
    const event = selectedEvent();
    const stage = event?.stage;
    const historical = run?.entry_mode === "injected_historical_fixture";
    const visible = Boolean(run?.tickets?.length) && (historical || ["delivered", "complete"].includes(stage));
    $("ticket-list").hidden = !visible;
    if (!visible) {
      $("ticket-list").replaceChildren();
      return;
    }
    const tickets = run.tickets.map((ticket) => ({ ...ticket, status: "VERIFIED" }));
    if (run.unauthorized_item && historical) {
      tickets.push({
        section: run.unauthorized_item.section,
        row: run.unauthorized_item.row,
        seat: run.unauthorized_item.seat,
        holder: "Not delivered to Alex",
        status: "QUARANTINED",
      });
    }
    $("ticket-list").replaceChildren(...tickets.map((ticket) => {
      const item = element("article");
      item.append(
        element("strong", "", `${ticket.section}-${ticket.row}-${ticket.seat}`),
        element("span", "", `The Midnight Signals · ${ticket.holder}`),
        element("b", "", ticket.status),
      );
      return item;
    }));
  }

  function renderReceipt() {
    const receipt = run?.receipt;
    const event = selectedEvent();
    const visible = Boolean(receipt) && Boolean(event) && (["complete", "customer_restored"].includes(event.stage) || (followLatest && run.terminal));
    $("receipt").hidden = !visible;
    if (!visible) return;
    $("receipt-id").textContent = receipt.receipt_id;
    $("receipt-instruction").textContent = `${receipt.instruction.quantity} tickets · ${usdc(receipt.instruction.maximum_usdc_units)} max`;
    $("receipt-purchase").textContent = `${receipt.purchase.quantity} ticket${receipt.purchase.quantity === 1 ? "" : "s"} · ${usd(receipt.purchase.total_usd_cents)}`;
    $("receipt-payment").textContent = `${usd(receipt.payment.merchant_received_usd_cents)} USD to merchant`;
    const recoveryLabels = {
      supplier_recovery_open: "supplier recovery open",
      belay_agent_error_absorbed: "Belay absorbs agent error",
    };
    $("receipt-outcome").textContent = receipt.outcome.remedy_usdc_units
      ? `${usdc(receipt.outcome.remedy_usdc_units)} remedy · ${recoveryLabels[receipt.outcome.recovery_state] || human(receipt.outcome.recovery_state)}`
      : `${human(receipt.outcome.delivery_state)} · no remedy`;
  }

  function renderSystemMap() {
    const event = selectedEvent();
    const technical = event?.technical || fallbackTechnical(event);
    $("active-layer").textContent = event ? technical.layer : "Awaiting authority";
    const map = document.querySelector(".system-nodes");
    let activeNode = null;
    document.querySelectorAll(".system-nodes article").forEach((node) => {
      node.classList.toggle("active", node.dataset.layer === technical.layer_id);
      if (node.classList.contains("active")) activeNode = node;
    });
    if (map && activeNode) {
      const target = activeNode.offsetLeft - (map.clientWidth - activeNode.offsetWidth) / 2;
      map.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
    }
  }

  function renderKnowledge(event) {
    const knowledge = event?.knowledge;
    $("knowledge-strip").hidden = !knowledge;
    if (!knowledge) return;
    $("provider-knowledge").textContent = human(knowledge.provider);
    $("belay-knowledge").textContent = human(knowledge.belay);
    $("safe-action").textContent = human(knowledge.safe_next_action);
  }

  function renderBackendEvent() {
    const event = selectedEvent();
    const technical = event?.technical || fallbackTechnical(event);
    $("event-layer").textContent = event ? technical.layer.toUpperCase() : "WAITING";
    $("event-actor").textContent = event?.actor || "No component has acted";
    $("request-method").textContent = event?.method || "—";
    $("request-status").textContent = event ? String(event.status) : "—";
    $("request-status").dataset.status = event ? String(event.status) : "";
    $("backend-event-title").textContent = event?.title || "Authorize a run to inspect the backend";
    $("backend-explanation").textContent = event?.explanation || "Each customer update will be paired with the exact infrastructure event that caused it.";
    $("event-from").textContent = event?.from || "Customer";
    $("event-to").textContent = event?.to || "Belay";
    $("request-url").textContent = event?.url || "No route selected";
    $("current-control").textContent = technical.control;
    $("current-money-effect").textContent = technical.money_effect;
    $("current-proof").textContent = technical.proof;
    $("current-retry").textContent = technical.retry_rule;
    renderKnowledge(event);
  }

  function paintJson(id, value) {
    const text = JSON.stringify(value ?? {}, null, 2);
    const fragment = document.createDocumentFragment();
    const expression = /("(?:\\.|[^"\\])*"\s*:?)|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?\b)/g;
    let offset = 0;
    for (const match of text.matchAll(expression)) {
      fragment.append(document.createTextNode(text.slice(offset, match.index)));
      const token = element("span");
      token.className = match[1]
        ? (match[1].endsWith(":") ? "json-key" : "json-string")
        : match[2] ? "json-bool" : "json-number";
      token.textContent = match[0];
      fragment.append(token);
      offset = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(offset)));
    $(id).replaceChildren(fragment);
  }

  function renderApiExchange() {
    const event = selectedEvent();
    paintJson("request-payload", event?.request || {});
    const response = event?.provider_observation
      ? { received_by_belay: event.response, simulator_provider_observation: event.provider_observation }
      : event?.response || {};
    paintJson("response-payload", response);
  }

  function renderPolicy() {
    const decision = viewStep() >= 3 ? run?.policy_decision : null;
    if (!decision) {
      $("policy-score").textContent = "Waiting";
      $("policy-reason").textContent = "The shopping model cannot approve itself. Exact checks appear when an offer and quote are ready.";
      $("control-groups").replaceChildren(...CORE_POLICY_GROUPS.map(([name]) => {
        const row = element("div");
        row.append(element("span", "", name), element("b", "", "WAIT"));
        return row;
      }));
      $("check-list").replaceChildren();
      $("all-checks").hidden = true;
      return;
    }
    const checks = decision.checks || [];
    const passed = checks.filter((check) => check.passed).length;
    $("policy-score").textContent = `${passed}/${checks.length} ${decision.allowed ? "passed" : "passed · blocked"}`;
    $("policy-reason").textContent = decision.reason;
    $("control-groups").replaceChildren(...CORE_POLICY_GROUPS.map(([name, names]) => {
      const subset = checks.filter((check) => names.includes(check.name));
      const okay = subset.length > 0 && subset.every((check) => check.passed);
      const row = element("div", okay ? "passed" : "failed");
      row.append(element("span", "", name), element("b", "", okay ? `${subset.length}/${subset.length}` : `${subset.filter((check) => check.passed).length}/${subset.length}`));
      return row;
    }));
    $("all-checks").hidden = false;
    $("check-list").replaceChildren(...checks.map((check) => {
      const row = element("article", check.passed ? "" : "failed");
      row.append(
        element("b", "", check.passed ? "PASS" : "FAIL"),
        element("span", "", human(check.name)),
        element("code", "", `expected ${safeText(check.expected)} · observed ${safeText(check.observed)}`),
      );
      return row;
    }));
  }

  function renderStatuses() {
    const event = selectedEvent();
    const state = event?.state_after || {};
    const statuses = {
      "funding-state": state.funding_state ?? run?.funding_state,
      "conversion-state": state.conversion_state ?? run?.conversion_state,
      "payout-state": state.payout_state ?? run?.payout_state,
      "order-state": state.order_state ?? run?.order_state,
      "delivery-state": state.delivery_state ?? run?.delivery_state,
      "protection-state": state.protection_state ?? run?.protection_state,
    };
    Object.entries(statuses).forEach(([id, value]) => {
      $(id).textContent = human(value);
      $(id).dataset.state = value || "not_started";
    });
    const previous = event?.state_before;
    const changed = previous
      ? Object.keys(state).filter((key) => previous[key] !== state[key])
      : [];
    $("state-delta").textContent = previous === null
      ? "Initial state"
      : changed.length ? `${changed.length} state ${changed.length === 1 ? "change" : "changes"}` : "No state change";
    const provider = event?.provider_after;
    $("payout-count").textContent = String(provider?.payout_state === "paid" ? 1 : followLatest ? run?.settlement?.provider_payout_count || 0 : 0);
    $("attempt-count").textContent = String(provider?.attempt_count || (followLatest ? run?.settlement?.provider_attempt_count || 0 : 0));
    $("latest-ledger-key").textContent = event?.ledger_keys?.at(-1) || "None in this event";
  }

  function renderChanges() {
    const event = selectedEvent();
    const changes = event?.balance_changes || [];
    $("change-count").textContent = `${changes.length} ${changes.length === 1 ? "account change" : "account changes"}`;
    if (!changes.length) {
      $("balance-changes").replaceChildren(element("p", "empty-state", "No account balance changed in this event."));
    } else {
      $("balance-changes").replaceChildren(...changes.map((change) => {
        const row = element("article");
        row.append(
          element("span", "", accountName(change.account)),
          element("strong", "", `${formatAccountAmount(change.asset, change.before_units)} → ${formatAccountAmount(change.asset, change.after_units)}`),
          element("small", "", `Delta ${change.delta_units >= 0 ? "+" : ""}${formatAccountAmount(change.asset, change.delta_units)}`),
        );
        return row;
      }));
    }

    const keys = new Set(event?.ledger_keys || []);
    const entries = (run?.ledger || []).filter((entry) => keys.has(entry.idempotency_key));
    if (!entries.length) {
      $("ledger-list").replaceChildren(element("p", "empty-state", "No value-moving ledger key was created."));
    } else {
      $("ledger-list").replaceChildren(...entries.map((entry) => {
        const row = element("article");
        const amount = entry.asset === "USDC_TO_USD_1_TO_1_DEMO"
          ? `${usdc(entry.units)} → ${usd(event?.provider_after?.net_usd_cents || run?.settlement?.merchant_received_usd_cents || 0)} USD`
          : formatAccountAmount(entry.asset, entry.units);
        row.append(
          element("span", "", `${accountName(entry.account_from)} → ${accountName(entry.account_to)}`),
          element("strong", "", amount),
          element("code", "", entry.idempotency_key),
        );
        return row;
      }));
    }
  }

  function proofRecord(label, reference, present) {
    const row = element("article", present ? "present" : "");
    row.append(
      element("i", "", present ? "✓" : "○"),
      (() => {
        const copy = element("div");
        copy.append(
          element("strong", "", label),
          element("span", "", present ? (reference || "Recorded") : "Waiting for this stage"),
        );
        return copy;
      })(),
      element("b", "", present ? "WRITTEN" : "PENDING"),
    );
    return row;
  }

  function renderProofs() {
    const event = selectedEvent();
    const step = viewStep();
    const state = event?.state_after || {};
    const provider = event?.provider_after;
    const claim = run?.claims?.at(-1);
    const historical = run?.entry_mode === "injected_historical_fixture";
    const records = [
      proofRecord("Customer authority", run?.grant?.signature, Boolean(run && step >= 0)),
      proofRecord("Admitted order", run?.admission?.operation_id, Boolean(run?.admission && step >= 3)),
      proofRecord("Signed settlement intent", run?.authorization?.intent_digest, Boolean(run?.authorization && step >= 4)),
      proofRecord("Provider / settlement", run?.settlement_record?.provider_reference || provider?.provider_reference, Boolean(provider?.payout_state === "paid" || run?.settlement_record && followLatest)),
      proofRecord("Delivery evidence", run?.delivery_record?.evidence_digest || human(state.delivery_state), Boolean(historical || (state.delivery_state && state.delivery_state !== "not_started"))),
      proofRecord("Protection claim", claim?.case_id, Boolean(claim && (state.protection_state?.includes("claim") || state.protection_state === "paid" || state.protection_state === "review_required"))),
      proofRecord("Linked receipt", run?.receipt?.receipt_id, Boolean(run?.receipt && (["complete", "customer_restored"].includes(event?.stage) || followLatest && run.terminal))),
    ];
    $("proof-stack").replaceChildren(...records);
    $("proof-count").textContent = `${records.filter((record) => record.classList.contains("present")).length}/${records.length} records`;
  }

  function renderCredentials() {
    if (!config) return;
    $("credential-list").replaceChildren(...(config.credentials || []).map((credential) => {
      const card = element("article");
      card.append(
        element("strong", "", credential.name),
        element("span", "", credential.holder),
        element("code", "", credential.key),
        element("p", "", credential.purpose),
      );
      return card;
    }));
    $("technical-notice").textContent = config.notice;
  }

  function renderInvestigation() {
    const finding = currentInvestigation();
    $("recovery-investigation").hidden = !needsPayoutInvestigation();
    $("investigation-summary").textContent = finding?.summary
      || "Check the provider's existing USD payout record before reconciling this purchase. This lookup cannot send, convert, or release funds.";
    $("investigation-verdict").textContent = finding ? human(finding.verdict) : "Awaiting evidence check";
    $("investigation-verdict").dataset.verdict = finding?.verdict || "pending";
    $("investigation-scope").textContent = finding?.scope || "Recovery Desk · deterministic evidence check · fictional provider";
    $("investigation-checks").replaceChildren(...(finding?.checks || []).map((check) => {
      const row = element("li", check.passed ? "passed" : "failed");
      row.append(element("b", "", check.passed ? "PASS" : "WAIT"), element("span", "", check.label));
      return row;
    }));
    $("investigation-observations").replaceChildren(...(finding?.observations || []).map((observation) => {
      const details = element("details");
      details.append(
        element("summary", "", observation.source),
        element("small", "", `Evidence digest: ${observation.digest}`),
        element("pre", "", JSON.stringify(observation.payload, null, 2)),
      );
      return details;
    }));
    $("investigation-next").textContent = canReconcilePayout()
      ? "The existing payout matches. Reconcile paid operation will check fresh evidence again and record the result; it will not send another payout."
      : "Reconciliation stays paused until the existing payout can be verified. Missing or conflicting evidence never authorizes a resend.";
  }

  function render() {
    if (!currentInvestigation()) investigation = null;
    updateButtons();
    renderInvestigation();
    renderProgress();
    renderScenario();
    renderTrace();
    renderLens();
    renderMoney();
    renderConversation();
    renderOffer();
    renderOutcome();
    renderTickets();
    renderReceipt();
    renderSystemMap();
    renderBackendEvent();
    renderPolicy();
    renderStatuses();
    renderApiExchange();
    renderChanges();
    renderProofs();
    renderCredentials();

    $("grant-state").textContent = run ? (run.terminal ? "CLOSED" : "ACTIVE") : "READY";
    $("grant-state").dataset.state = run?.terminal ? "closed" : run ? "active" : "ready";
    $("customer-connection").classList.toggle("active", Boolean(run));
    $("entry-mode").textContent = run?.entry_mode === "injected_historical_fixture" ? "HISTORICAL FIXTURE" : "GUARDED MODE";
    $("run-short-id").textContent = run ? run.id.slice(0, 12).toUpperCase() : "NO RUN";
    $("operation-id").textContent = run?.operation_id || "Allocated after authorization";
    $("order-id").textContent = run?.order_id || "Allocated after authorization";
    $("mode-id").textContent = run?.entry_mode || "live_guarded_simulation";
  }

  function playbackDelay() {
    const stage = run?.stage;
    if (["admitted", "merchant_paid", "non_delivery", "claim_approved", "customer_restored", "complete"].includes(stage)) return 2600;
    return 1750;
  }

  function scheduleAdvance() {
    if (!playing || busy || !run?.can_advance || run.terminal || requiresManualAction()) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => advance(true), playbackDelay());
  }

  async function advance(automatic = false) {
    if (busy || !run || run.terminal || !run.can_advance) return;
    if (automatic && requiresManualAction()) return;
    if (needsPayoutInvestigation() && !canReconcilePayout()) return;
    const restoreNextFocus = !automatic && document.activeElement === $("next");
    busy = true;
    showError();
    updateButtons();
    try {
      run = await api(`/api/runs/${encodeURIComponent(run.id)}/advance`, {
        expected_revision: run.revision,
      });
      followLatest = true;
      selectedEventId = null;
      render();
      if (run.terminal || requiresManualAction()) {
        stopPlayback();
        updateButtons();
        if (run.terminal && !automatic) (run.receipt ? $("receipt") : $("outcome")).focus();
      }
    } catch (error) {
      stopPlayback();
      showError(`${error.message} The simulator paused and did not automatically repeat a money-moving request.`);
    } finally {
      busy = false;
      updateButtons();
      if (restoreNextFocus && run?.can_advance && !run.terminal) $("next").focus();
      if (isUnknown()) $("next").focus();
    }
    scheduleAdvance();
  }

  async function investigatePayout() {
    if (busy || !needsPayoutInvestigation()) return;
    const runId = run.id;
    const revision = run.revision;
    busy = true;
    investigation = null;
    showError();
    render();
    try {
      const finding = await api(`/api/runs/${encodeURIComponent(runId)}/investigate`, { expected_revision: revision });
      if (run?.id !== runId || run?.revision !== revision) return;
      const blockedIntent = finding.operation_id === null && finding.verdict === "unknown" && finding.can_reconcile === false;
      if (finding.schema_version !== "belay.purchase.investigation.v1"
        || finding.run_id !== runId || finding.revision !== revision
        || (finding.operation_id !== run.operation_id && !blockedIntent)
        || !["paid", "unknown", "conflict"].includes(finding.verdict)
        || !Array.isArray(finding.checks) || !Array.isArray(finding.observations)) {
        throw new Error("The investigation did not match this purchase revision. Check the evidence again.");
      }
      investigation = finding;
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      render();
      if (canReconcilePayout()) $("next").focus();
    }
  }

  $("mission-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || run) return;
    busy = true;
    showError();
    updateButtons();
    try {
      run = await api("/api/runs", {
        scenario: $("scenario").value,
        budget_cents: 30_000,
        quantity: 2,
      });
      remember(run.id);
      followLatest = true;
      selectedEventId = null;
      playing = true;
      render();
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      updateButtons();
    }
    scheduleAdvance();
  });

  $("next").addEventListener("click", () => advance(false));
  $("investigate").addEventListener("click", investigatePayout);
  $("play").addEventListener("click", () => {
    if (playing) {
      stopPlayback();
      updateButtons();
      return;
    }
    if (!busy && run?.can_advance && !run.terminal && !requiresManualAction()) {
      playing = true;
      followLatest = true;
      selectedEventId = null;
      render();
      scheduleAdvance();
    }
  });
  $("reset").addEventListener("click", () => {
    if (busy || !run) return;
    stopPlayback();
    run = null;
    followLatest = true;
    selectedEventId = null;
    remember(null);
    showError();
    render();
    $("scenario").focus();
  });
  $("scenario").addEventListener("change", renderScenario);
  $("event-select").addEventListener("change", () => {
    selectedEventId = $("event-select").value;
    followLatest = selectedEventId === latestEvent()?.id;
    render();
  });
  $("return-live").addEventListener("click", () => {
    followLatest = true;
    selectedEventId = null;
    render();
  });

  function setMobileView(view) {
    $("simulator").querySelector(".workspace").dataset.mobileView = view;
    $("view-customer").setAttribute("aria-selected", String(view === "customer"));
    $("view-backend").setAttribute("aria-selected", String(view === "backend"));
  }
  $("view-customer").addEventListener("click", () => setMobileView("customer"));
  $("view-backend").addEventListener("click", () => setMobileView("backend"));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPlayback();
      updateButtons();
    }
  });

  async function initialize() {
    busy = true;
    render();
    try {
      config = await api("/api/config");
      $("scenario").replaceChildren(...config.scenarios.map((scenario) => {
        const option = element("option", "", scenario.label);
        option.value = scenario.id;
        return option;
      }));
      $("scenario").value = config.scenarios.some((item) => item.id === "non_delivery_paid")
        ? "non_delivery_paid"
        : config.scenarios[0]?.id;
      renderScenario();
      renderCredentials();
      const saved = recalled();
      if (saved && /^[a-f0-9]{32}$/.test(saved)) {
        try {
          run = await api(`/api/runs/${encodeURIComponent(saved)}`);
          $("scenario").value = run.scenario;
          followLatest = true;
          selectedEventId = null;
          renderScenario();
        } catch {
          remember(null);
          showError("The saved walkthrough belongs to an older or unavailable demo. Start a new run.");
        }
      }
    } catch (error) {
      showError(`Could not connect to the local simulator: ${error.message}`);
    } finally {
      busy = false;
      render();
    }
  }

  initialize();
})();
