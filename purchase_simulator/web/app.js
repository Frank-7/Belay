(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = "belay-protected-purchase-v03-run";
  const USDC_SCALE = 1_000_000;
  let run = null;
  let config = null;
  let busy = false;
  let playing = false;
  let timer = null;
  let payloadSide = "request";

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
    customer_available: "Customer",
    order_hold: "Order hold",
    provider_in_transit: "Provider",
    merchant_received: "Merchant",
    protection_reserve: "Protection reserve",
  })[value] || human(value || "System");

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
        render();
      }
      throw new Error(result.error || `Local request failed (${response.status}).`);
    }
    return result;
  }

  function stopPlayback() {
    playing = false;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function isUnknown() {
    return run?.payout_state === "unknown";
  }

  function updateButtons() {
    const actionable = run && !run.terminal && run.can_advance;
    $("start").disabled = busy || Boolean(run);
    $("scenario").disabled = busy || Boolean(run);
    $("play").disabled = busy || !actionable;
    $("next").disabled = busy || !actionable || playing;
    $("reset").disabled = busy || !run;
    $("play").textContent = playing ? "Pause" : "Play automatically";
    $("next").textContent = isUnknown() ? "Reconcile exact payout →" : "Next step →";
  }

  function renderProgress() {
    const current = run?.step || 0;
    const maximum = run?.max_step || 13;
    const percent = run?.terminal ? 100 : Math.min(100, Math.round((current / maximum) * 100));
    $("progress").setAttribute("aria-valuemax", String(maximum));
    $("progress").setAttribute("aria-valuenow", String(current));
    $("progress").querySelector("span").style.width = `${percent}%`;
    $("step-count").textContent = run ? `STEP ${String(current).padStart(2, "0")} OF ${String(maximum).padStart(2, "0")}` : "READY";
    $("current-stage").textContent = run?.title || "Authorize the mission to begin";
    $("stage-dot").dataset.kind = run?.outcome?.kind || "idle";
  }

  function markNode(id, amount, uncertain = false) {
    const node = $(id);
    node.classList.toggle("has-value", Number(amount) > 0);
    node.classList.toggle("uncertain", uncertain);
  }

  function renderMoney() {
    const buyer = run?.buyer?.available_usdc_units ?? 300 * USDC_SCALE;
    const held = run?.buyer?.held_usdc_units ?? 0;
    const transit = run?.settlement?.provider_in_transit_usdc_units ?? 0;
    const merchant = run?.settlement?.merchant_received_usd_cents ?? 0;
    const observed = run?.settlement?.provider_observed_usd_cents ?? 0;
    const needsReconciliation = observed > 0 && merchant === 0;
    const protection = run?.protection || {
      reserve_cash_usdc_units: 1_000 * USDC_SCALE,
      available_usdc_units: 1_000 * USDC_SCALE,
      committed_usdc_units: 0,
      pending_usdc_units: 0,
      paid_usdc_units: 0,
    };

    $("buyer-balance").textContent = usdc(buyer);
    $("held-balance").textContent = usdc(held);
    $("provider-balance").textContent = usdc(transit);
    $("provider-note").textContent = needsReconciliation
      ? "Provider record observed · Belay ledger pending"
      : isUnknown() ? "Belay ledger · outcome unknown" : "USDC → USD adapter";
    $("merchant-balance").textContent = `${usd(merchant || observed)} USD`;
    $("merchant-note").textContent = needsReconciliation
      ? "Provider record: paid · Belay reconciling"
      : "Northstar Tickets";
    $("reserve-cash").textContent = `${usdc(protection.reserve_cash_usdc_units)} cash`;
    $("reserve-available").textContent = usdc(protection.available_usdc_units);
    $("reserve-committed").textContent = usdc(protection.committed_usdc_units);
    $("reserve-pending").textContent = usdc(protection.pending_usdc_units);
    $("reserve-paid").textContent = usdc(protection.paid_usdc_units);

    markNode("buyer-node", buyer);
    markNode("hold-node", held);
    markNode("provider-node", transit, isUnknown() || needsReconciliation);
    markNode("merchant-node", merchant || observed, needsReconciliation);
    $("merchant-node").title = needsReconciliation
      ? `${usd(observed)} is visible in the fictional provider record but not yet reconciled into Belay's ledger.`
      : "Merchant USD confirmed by Belay.";
  }

  function renderOffer() {
    const offer = run?.offer;
    $("offer-card").hidden = !offer;
    if (!offer) return;
    $("offer-quantity").textContent = `${offer.quantity} adjacent ticket${offer.quantity === 1 ? "" : "s"}`;
    $("offer-price").textContent = `${usd(offer.total_usd_cents)} USD`;
    $("offer-seats").textContent = offer.seats.join(" · ");
    const decision = run.policy_decision;
    const violation = decision?.allowed === false;
    $("offer-status").textContent = !decision
      ? "Agent proposal"
      : decision.allowed ? "All controls passed" : "Does not match grant";
    $("offer-status").classList.toggle("danger", violation);
    $("offer-card").classList.toggle("violation", violation);
  }

  function renderOutcome() {
    const outcome = run?.outcome || {
      kind: "active",
      headline: "Mission not started",
      detail: "No money has moved.",
    };
    $("outcome").className = `outcome ${outcome.kind}`;
    $("outcome-headline").textContent = outcome.headline;
    $("outcome-detail").textContent = outcome.detail;
    const icons = { success: "✓", remedied: "↺", blocked: "×", warning: "!", review: "?", safe: "✓", active: "○" };
    $("outcome").querySelector(".outcome-icon").textContent = icons[outcome.kind] || "○";
  }

  function renderTickets() {
    const tickets = run?.tickets || [];
    $("ticket-list").hidden = !tickets.length;
    $("ticket-list").replaceChildren(...tickets.map((ticket) => {
      const item = document.createElement("article");
      const seat = document.createElement("strong");
      seat.textContent = `${ticket.section}-${ticket.row}-${ticket.seat}`;
      const copy = document.createElement("span");
      copy.textContent = `The Midnight Signals · ${ticket.holder}`;
      const mark = document.createElement("b");
      mark.textContent = "VERIFIED";
      item.append(seat, copy, mark);
      return item;
    }));
  }

  function renderReceipt() {
    const receipt = run?.receipt;
    $("receipt").hidden = !receipt;
    if (!receipt) return;
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

  function renderStatuses() {
    const statuses = {
      "funding-state": run?.funding_state,
      "conversion-state": run?.conversion_state,
      "payout-state": run?.payout_state,
      "order-state": run?.order_state,
      "delivery-state": run?.delivery_state,
      "protection-state": run?.protection_state,
    };
    Object.entries(statuses).forEach(([id, value]) => {
      $(id).textContent = human(value);
      $(id).dataset.state = value || "not_started";
    });
    $("payout-count").textContent = String(run?.settlement?.provider_payout_count || 0);
    $("attempt-count").textContent = String(run?.settlement?.provider_attempt_count || 0);
    const historical = run?.entry_mode === "injected_historical_fixture";
    $("entry-mode").textContent = historical ? "Injected fixture" : "Guarded";
    $("entry-note").textContent = historical ? "starts after prior payment" : "live policy path";
    $("entry-mode").classList.toggle("fixture", historical);
  }

  function renderLedger() {
    const entries = run?.ledger || [];
    $("ledger-count").textContent = `${entries.length} ${entries.length === 1 ? "entry" : "entries"}`;
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No funds have moved.";
      $("ledger-list").replaceChildren(empty);
      return;
    }
    $("ledger-list").replaceChildren(...entries.map((entry) => {
      const row = document.createElement("div");
      const route = document.createElement("span");
      route.textContent = `${accountName(entry.account_from)} → ${accountName(entry.account_to)}`;
      const amount = document.createElement("strong");
      amount.textContent = entry.asset === "USDC_TO_USD_1_TO_1_DEMO"
        ? `${usdc(entry.units)} → ${usd(run?.settlement?.merchant_received_usd_cents)} USD`
        : usdc(entry.units);
      const kind = document.createElement("small");
      kind.textContent = human(entry.kind);
      row.append(route, amount, kind);
      return row;
    }));
  }

  function renderTrace() {
    const events = run?.events || [];
    $("event-count").textContent = `${events.length} ${events.length === 1 ? "event" : "events"}`;
    $("trace-list").replaceChildren(...events.map((event, index) => {
      const item = document.createElement("li");
      if (index === events.length - 1) item.className = "current";
      const number = document.createElement("b");
      number.textContent = String(event.step).padStart(2, "0");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = event.title;
      const actor = document.createElement("span");
      actor.textContent = `${event.actor} · ${event.method}`;
      copy.append(title, actor);
      item.append(number, copy);
      return item;
    }));
    const selected = $("event-select").value;
    $("event-select").replaceChildren(...events.map((event) => {
      const option = document.createElement("option");
      option.value = event.id;
      option.textContent = `${String(event.step).padStart(2, "0")} · ${event.title}`;
      return option;
    }));
    if (events.length) {
      $("event-select").value = events.some((event) => event.id === selected)
        ? selected
        : events.at(-1).id;
    }
    renderInspector();
  }

  function paintJson(value) {
    const text = JSON.stringify(value ?? {}, null, 2);
    const fragment = document.createDocumentFragment();
    const expression = /("(?:\\.|[^"\\])*"\s*:?)|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?\b)/g;
    let offset = 0;
    for (const match of text.matchAll(expression)) {
      fragment.append(document.createTextNode(text.slice(offset, match.index)));
      const token = document.createElement("span");
      token.className = match[1]
        ? (match[1].endsWith(":") ? "json-key" : "json-string")
        : match[2] ? "json-bool" : "json-number";
      token.textContent = match[0];
      fragment.append(token);
      offset = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(offset)));
    $("payload").replaceChildren(fragment);
  }

  function renderInspector() {
    const events = run?.events || [];
    const event = events.find((item) => item.id === $("event-select").value) || events.at(-1);
    if (!event) {
      $("request-method").textContent = "—";
      $("request-url").textContent = "No event selected";
      $("request-status").textContent = "";
      $("request-explanation").textContent = "";
      paintJson({});
      return;
    }
    $("request-method").textContent = event.method;
    $("request-url").textContent = event.url;
    $("request-status").textContent = String(event.status);
    $("request-status").dataset.status = String(event.status);
    $("request-explanation").textContent = event.explanation;
    paintJson(event[payloadSide]);
  }

  function renderCredentials() {
    if (!config) return;
    $("credential-list").replaceChildren(...(config.credentials || []).map((credential) => {
      const card = document.createElement("article");
      const title = document.createElement("strong");
      title.textContent = credential.name;
      const holder = document.createElement("span");
      holder.textContent = credential.holder;
      const key = document.createElement("code");
      key.textContent = credential.key;
      const purpose = document.createElement("p");
      purpose.textContent = credential.purpose;
      card.append(title, holder, key, purpose);
      return card;
    }));
    $("technical-notice").textContent = config.notice;
  }

  function render() {
    updateButtons();
    renderProgress();
    renderMoney();
    renderOffer();
    renderOutcome();
    renderTickets();
    renderReceipt();
    renderStatuses();
    renderLedger();
    renderTrace();
    renderCredentials();

    $("agent-message").textContent = run?.user_message
      || "Choose a scenario and authorize the mission. I will explain each action in plain language.";
    $("grant-state").textContent = run ? (run.terminal ? "Closed" : "Active") : "Ready";
    $("grant-state").dataset.state = run?.terminal ? "closed" : run ? "active" : "ready";
    $("operation-id").textContent = run?.operation_id || "Allocated after authorization";
    $("order-id").textContent = run?.order_id || "Allocated after authorization";
    $("mode-id").textContent = run?.entry_mode || "live_guarded_simulation";
  }

  async function advance() {
    if (busy || !run || run.terminal || !run.can_advance) return;
    busy = true;
    showError();
    updateButtons();
    try {
      run = await api(`/api/runs/${encodeURIComponent(run.id)}/advance`, {
        expected_revision: run.revision,
      });
      render();
      if (run.terminal || isUnknown() || run.manual_review) stopPlayback();
    } catch (error) {
      stopPlayback();
      showError(`${error.message} The simulator paused and did not automatically repeat a money-moving request.`);
    } finally {
      busy = false;
      updateButtons();
      if (isUnknown()) $("next").focus();
    }
    if (playing) timer = setTimeout(advance, 1050);
  }

  function scenarioDescription() {
    const scenario = config?.scenarios?.find((item) => item.id === $("scenario").value);
    $("scenario-description").textContent = scenario?.description || "Select a scenario to test Belay's controls.";
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
      render();
      $("next").focus();
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      updateButtons();
    }
  });

  $("next").addEventListener("click", advance);
  $("play").addEventListener("click", () => {
    if (playing) {
      stopPlayback();
      updateButtons();
      return;
    }
    if (!busy && run?.can_advance) {
      playing = true;
      updateButtons();
      advance();
    }
  });
  $("reset").addEventListener("click", () => {
    if (busy || !run) return;
    stopPlayback();
    run = null;
    remember(null);
    showError();
    render();
    $("scenario").focus();
  });
  $("scenario").addEventListener("change", scenarioDescription);
  $("event-select").addEventListener("change", renderInspector);
  $("request-tab").addEventListener("click", () => {
    payloadSide = "request";
    $("request-tab").setAttribute("aria-pressed", "true");
    $("response-tab").setAttribute("aria-pressed", "false");
    renderInspector();
  });
  $("response-tab").addEventListener("click", () => {
    payloadSide = "response";
    $("request-tab").setAttribute("aria-pressed", "false");
    $("response-tab").setAttribute("aria-pressed", "true");
    renderInspector();
  });
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
        const option = document.createElement("option");
        option.value = scenario.id;
        option.textContent = scenario.label;
        return option;
      }));
      scenarioDescription();
      renderCredentials();
      const saved = recalled();
      if (saved && /^[a-f0-9]{32}$/.test(saved)) {
        try {
          run = await api(`/api/runs/${encodeURIComponent(saved)}`);
          $("scenario").value = run.scenario;
          scenarioDescription();
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
