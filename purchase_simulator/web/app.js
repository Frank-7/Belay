(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const money = (cents) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(cents || 0) / 100);
  const human = (value) => String(value ?? 'Not started').replaceAll('_', ' ');
  const storageKey = 'belay-purchase-simulator-run';
  const names = ['Mission authorized', 'Request offers', 'Exact checkout', 'Check and sign', 'Payment mandates', 'Scoped token', 'Submit checkout', 'Payment processor', 'Issuer request', 'Bank decision', 'Receipts and delivery', 'Notify you'];
  let run = null, config = null, busy = false, playing = false, timer = null, selectedEvent = null, payloadTab = 'request';
  function error(message = '') { $('error').textContent = message; $('error').hidden = !message; }
  function remember(value) { try { value ? localStorage.setItem(storageKey, value) : localStorage.removeItem(storageKey); } catch { /* Persistence is optional in private browsing. */ } }
  function recalled() { try { return localStorage.getItem(storageKey); } catch { return null; } }
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) {
      if (result.current) { run = result.current; render(); }
      throw new Error(result.error || `Local request failed (${response.status}).`);
    }
    return result;
  }
  function stop() { playing = false; clearTimeout(timer); timer = null; }
  function unknown() { return run && [run.payment_status, run.order_status].some((v) => String(v).includes('unknown')); }
  function buttons() {
    $('start').disabled = busy || !!run;
    $('scenario').disabled = busy || !!run;
    $('budget').disabled = busy || !!run;
    $('play').disabled = busy || !run || run.terminal || run.needs_verification || !run.can_advance;
    $('next').disabled = busy || !run || run.terminal || run.needs_verification || !run.can_advance || playing;
    $('verify').disabled = busy || !run?.needs_verification;
    $('reset').disabled = busy || !run || !run.terminal;
    $('play').textContent = playing ? 'Pause' : 'Play through';
    $('next').textContent = unknown() ? 'Reconcile purchase →' : 'Next step →';
  }
  function code(value) {
    const text = JSON.stringify(value ?? {}, null, 2);
    const fragment = document.createDocumentFragment();
    const expression = /("(?:\\.|[^"\\])*"\s*:?)|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?\b)/g;
    let offset = 0;
    for (const match of text.matchAll(expression)) {
      fragment.append(document.createTextNode(text.slice(offset, match.index)));
      const token = document.createElement('span');
      token.className = match[1] ? (match[1].endsWith(':') ? 'json-key' : 'json-string') : match[2] ? 'json-bool' : 'json-number';
      token.textContent = match[0]; fragment.append(token); offset = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(offset)));
    $('payload').replaceChildren(fragment);
  }
  function detail(chooseDefault = false) {
    const events = run?.events || [];
    const event = events.find((item) => String(item.id) === String(selectedEvent)) || events.at(-1);
    if (!event) return;
    if (chooseDefault || String(event.id) !== String(selectedEvent)) payloadTab = Object.keys(event.request || {}).length ? 'request' : 'response';
    selectedEvent = event.id;
    $('event-select').value = String(event.id);
    $('request-number').textContent = event.step;
    $('request-title').textContent = event.title;
    $('request-status').textContent = event.status ?? 'RECORDED';
    $('request-route').textContent = [event.from || event.actor, event.to].filter(Boolean).join(' → ');
    $('request-method').textContent = event.method || 'INTERNAL';
    $('request-url').textContent = event.url || 'belay.executor';
    $('request-explanation').textContent = event.explanation || '';
    $('request-tab').classList.toggle('active', payloadTab === 'request');
    $('response-tab').classList.toggle('active', payloadTab === 'response');
    $('request-tab').setAttribute('aria-selected', String(payloadTab === 'request'));
    $('response-tab').setAttribute('aria-selected', String(payloadTab === 'response'));
    $('payload').setAttribute('aria-labelledby', `${payloadTab}-tab`);
    code(event[payloadTab]);
  }
  function render() {
    buttons();
    const budget = run?.mission?.budget_cents ?? Number($('budget').value) * 100;
    $('mission-bubble').replaceChildren(document.createTextNode('Find two adjacent tickets for The Midnight Signals at Harbor Hall on October 24. Stay under '));
    const amount = document.createElement('strong'); amount.textContent = `${money(budget)} total`;
    $('mission-bubble').append(amount, document.createTextNode(', including fees.'));
    $('current-stage').textContent = run?.title || 'Ready when you are';
    $('step-count').textContent = `${run?.step ?? 0} / 11`;
    $('live-dot').className = 'live-dot' + (run ? (unknown() || run.needs_verification || (run.terminal && !run.tickets?.length) ? ' warning' : run.terminal ? ' done' : ' running') : '');
    $('step-track').replaceChildren(...names.map((name, i) => { const piece = document.createElement('div'); piece.className = 'step-segment' + (run && i < run.step ? ' complete' : run && i === run.step ? ' current' : ''); piece.title = `${i}. ${name}`; return piece; }));
    $('consent-heading').textContent = run ? `Authorized · ${money(budget)} maximum` : 'Your mission, your boundaries';
    $('agent-status').textContent = !run ? 'Ready to help' : run.needs_verification ? 'Waiting for your bank' : unknown() ? 'Checking the purchase' : run.terminal ? 'Mission finished' : 'Working within your limits';
    $('agent-message').textContent = run?.user_message || 'Authorize the mission above. I can then buy tickets that meet your rules without asking you to approve each checkout.';
    $('offer').hidden = !run?.offer;
    if (run?.offer) {
      $('offer-price').textContent = money(run.offer.total_cents);
      const delivered = String(run.delivery_status).includes('delivered');
      const over = run.offer.total_cents > budget;
      $('offer-tag').textContent = delivered ? 'Tickets delivered' : over ? 'Over your limit' : unknown() ? 'Checking outcome' : 'Within your limit';
      $('offer-tag').className = 'tag ' + (over || unknown() ? 'warning' : delivered ? 'success' : '');
    }
    $('bank-challenge').hidden = !run?.needs_verification;
    $('tickets').hidden = !run?.tickets?.length;
    $('tickets').replaceChildren(...(run?.tickets || []).map((ticket) => {
      const item = document.createElement('div'); item.className = 'ticket';
      const title = document.createElement('strong'); title.textContent = '✓ Demo ticket delivered';
      const event = document.createElement('span'); event.textContent = ticket.event || 'The Midnight Signals';
      const seat = document.createElement('span'); seat.className = 'ticket-seats'; seat.textContent = `Row ${ticket.row || 'H'} · Seat ${ticket.seat}`;
      const section = document.createElement('span'); section.textContent = `Section ${ticket.section || '102'} · Not valid for entry`;
      item.append(title, event, seat, section); return item;
    }));
    $('customer-outcome').textContent = !run ? 'No purchase started' : unknown() ? 'Outcome pending · no repeat purchase' : run.needs_verification ? 'Action required by your bank' : run.tickets?.length ? `${run.tickets.length} tickets delivered · ${money(run.budget?.spent_cents)}` : run.terminal ? 'Purchase stopped · no tickets bought' : 'Mission active';
    for (const [id, key] of [['payment-state','payment_status'], ['order-state','order_status'], ['delivery-state','delivery_status']]) { $(id).textContent = human(run?.[key]); $(id).dataset.state = run?.[key] || ''; }
    $('reserved').textContent = money(run?.budget?.reserved_cents);
    $('spent').textContent = money(run?.budget?.spent_cents);
    $('charge-count').textContent = run?.provider_charge_count ?? 0;
    $('operation-id').textContent = run?.operation_id || 'Allocated when you authorize';
    const events = run?.events || [];
    $('trace-empty').hidden = events.length > 0;
    $('trace-content').hidden = !events.length;
    $('event-count').textContent = events.length ? `${events.length} recorded events` : 'No events yet';
    $('event-select').replaceChildren(...events.map((event) => { const option = document.createElement('option'); option.value = event.id; option.textContent = `${event.step}. ${event.title}`; return option; }));
    detail();
  }
  async function advance(verify = false) {
    if (busy || !run || run.terminal) return;
    busy = true; buttons(); error();
    try {
      run = await api(`/api/runs/${encodeURIComponent(run.id)}/${verify ? 'verify' : 'advance'}`, { expected_revision: run.revision });
      selectedEvent = null;
      if (run.terminal || run.needs_verification || unknown()) stop();
      render();
    } catch (e) { stop(); error(`${e.message} The simulator has paused; it has not automatically repeated the request.`); }
    finally { busy = false; buttons(); }
    if (playing) timer = setTimeout(() => advance(), 1500);
  }
  function scenarioDescription() {
    $('scenario-description').textContent = config?.scenarios?.find((s) => s.id === $('scenario').value)?.description || 'Two adjacent seats. All fees included.';
  }
  $('mission-form').addEventListener('submit', async (event) => {
    event.preventDefault(); if (busy || run) return;
    const cents = Math.round(Number($('budget').value) * 100);
    if (!Number.isSafeInteger(cents) || cents < 100 || cents > 1000000) { error('Enter a budget between $1 and $10,000.'); return; }
    busy = true; buttons(); error();
    try { run = await api('/api/runs', { scenario: $('scenario').value, budget_cents: cents, quantity: 2 }); remember(run.id); selectedEvent = null; render(); }
    catch (e) { error(e.message); }
    finally { busy = false; buttons(); }
  });
  $('next').addEventListener('click', () => advance());
  $('verify').addEventListener('click', () => advance(true));
  $('play').addEventListener('click', () => { if (playing) { stop(); buttons(); } else if (!busy && run?.can_advance) { playing = true; advance(); } });
  $('reset').addEventListener('click', () => { if (busy || !run?.terminal) return; stop(); run = null; selectedEvent = null; remember(null); error(); render(); });
  $('event-select').addEventListener('change', () => { selectedEvent = $('event-select').value; detail(true); });
  $('latest').addEventListener('click', () => { selectedEvent = null; detail(); });
  $('request-tab').addEventListener('click', () => { payloadTab = 'request'; detail(); });
  $('response-tab').addEventListener('click', () => { payloadTab = 'response'; detail(); });
  $('keys-toggle').addEventListener('click', () => { const open = $('credentials').hidden; $('credentials').hidden = !open; $('keys-toggle').setAttribute('aria-expanded', String(open)); });
  $('scenario').addEventListener('change', scenarioDescription);
  $('budget').addEventListener('input', () => { if (!run) render(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && playing) { stop(); buttons(); } });
  async function initialize() {
    busy = true; render();
    try {
      config = await api('/api/config');
      if (config.scenarios?.length) $('scenario').replaceChildren(...config.scenarios.map((scenario) => { const option = document.createElement('option'); option.value = scenario.id; option.textContent = scenario.label; return option; }));
      $('credential-list').replaceChildren(...(config.credentials || []).map((credential) => { const item = document.createElement('div'); item.className = 'credential'; const title = document.createElement('strong'); title.textContent = `${credential.name} · ${credential.holder}`; const key = document.createElement('code'); key.textContent = credential.key; const purpose = document.createElement('span'); purpose.textContent = credential.purpose; item.append(title, key, purpose); return item; }));
      scenarioDescription();
      const saved = recalled();
      if (saved && /^[a-f0-9-]{20,64}$/.test(saved)) {
        try { run = await api(`/api/runs/${encodeURIComponent(saved)}`); $('scenario').value = run.scenario; $('budget').value = run.mission.budget_cents / 100; }
        catch { remember(null); error('The previous simulation could not be loaded. You can authorize a new one.'); }
      }
    } catch (e) { error(`Could not connect to the local simulator: ${e.message}`); }
    finally { busy = false; render(); }
  }
  initialize();
})();
