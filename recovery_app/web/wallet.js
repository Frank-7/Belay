// Public testnet only. MetaMask keeps the keys and asks the person to sign.
export const arcNetwork = Object.freeze({
  chainId: '0x4cef52', chainName: 'Arc Testnet',
  nativeCurrency: { name: 'Test USDC', symbol: 'USDC', decimals: 18 },
  rpcUrls: ['https://rpc.testnet.arc.io'],
  blockExplorerUrls: ['https://testnet.arcscan.app'],
});
const TOKEN = '0x3600000000000000000000000000000000000000';
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const HASH = /^0x[0-9a-fA-F]{64}$/;

function normalizedAddress(value) {
  if (!ADDRESS.test(value) || /^0x0{40}$/i.test(value)) throw new Error('Enter a complete test wallet address.');
  return value.toLowerCase();
}

export function parseAmount(value) {
  if (!/^(?:0(?:\.[0-9]{1,2})?|1(?:\.0{1,2})?)$/.test(String(value))) {
    throw new Error('Choose 0.01 to 1 test USDC, with at most two decimal places.');
  }
  const units = Math.round(Number(value) * 1_000_000);
  if (!Number.isInteger(units) || units < 10_000 || units > 1_000_000 || units % 10_000) {
    throw new Error('Choose 0.01 to 1 test USDC in steps of 0.01.');
  }
  return units;
}

function injectedWallet() {
  const injected = window.ethereum;
  const wallet = injected?.providers?.find(provider => provider.isMetaMask) || injected;
  if (!wallet?.request) throw new Error('Open this local app in a browser with MetaMask installed, then connect a separate test wallet.');
  return wallet;
}

async function ensureArc(wallet) {
  if ((await wallet.request({ method: 'eth_chainId' })).toLowerCase() !== arcNetwork.chainId) {
    try {
      await wallet.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: arcNetwork.chainId }] });
    } catch (error) {
      if (error.code !== 4902) throw error;
      await wallet.request({ method: 'wallet_addEthereumChain', params: [arcNetwork] });
      await wallet.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: arcNetwork.chainId }] });
    }
  }
  if ((await wallet.request({ method: 'eth_chainId' })).toLowerCase() !== arcNetwork.chainId) {
    throw new Error('This demo only sends on Arc Testnet.');
  }
}

export async function connectWallet() {
  const wallet = injectedWallet();
  const accounts = await wallet.request({ method: 'eth_requestAccounts' });
  if (!Array.isArray(accounts) || !accounts.length) throw new Error('No wallet account was selected.');
  await ensureArc(wallet);
  const sender = normalizedAddress(accounts[0]);
  let balance = null;
  try {
    const encoded = await wallet.request({ method: 'eth_call', params: [{
      to: TOKEN, data: '0x70a08231' + sender.slice(2).padStart(64, '0'),
    }, 'latest'] });
    const units = BigInt(encoded);
    balance = `${units / 1_000_000n}.${(units % 1_000_000n).toString().padStart(6, '0')}`;
  } catch { /* A balance display failure is not authority to send or retry. */ }
  return { sender, balance };
}

async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'The local recovery service could not complete this step.');
  return payload;
}

function validatedTransaction(transaction, { sender, recipient, amountUnits }) {
  if (!transaction || typeof transaction !== 'object') throw new Error('The saved incident has no unsigned transaction.');
  const data = '0xa9059cbb' + recipient.slice(2).padStart(64, '0') + amountUnits.toString(16).padStart(64, '0');
  if (transaction.chainId !== arcNetwork.chainId
      || normalizedAddress(transaction.from) !== sender
      || normalizedAddress(transaction.to) !== TOKEN
      || transaction.value !== '0x0' || transaction.data?.toLowerCase() !== data) {
    throw new Error('The transaction differs from your chosen testnet transfer. No wallet request was made.');
  }
  // Copy exactly this allowlist, not extra server fields such as permissions.
  return { chainId: arcNetwork.chainId, from: sender, to: TOKEN, value: '0x0', data };
}

export async function attachTransaction(incidentId, hash) {
  if (!/^[a-f0-9]{32}$/.test(incidentId)) throw new Error('Invalid incident identifier.');
  if (!HASH.test(hash)) throw new Error('Paste the complete original transaction hash from MetaMask.');
  return post(`/api/wallet/${incidentId}/transaction`, { transaction_hash: hash.toLowerCase() });
}

export async function checkResolvedTransfer(incidentId) {
  if (!/^[a-f0-9]{32}$/.test(incidentId)) throw new Error('Invalid incident identifier.');
  const response = await fetch(`/api/incidents/${incidentId}`, { credentials: 'same-origin', cache: 'no-store' });
  const incident = await response.json();
  if (!response.ok) throw new Error(incident.error || 'The previous incident could not be checked.');
  if (incident.id !== incidentId || incident.provider !== 'arc' || incident.status !== 'resolved') {
    throw new Error('Resolve the previous wallet incident before starting another transfer. Inspect its original activity; do not send again while its outcome is unknown.');
  }
  return incident;
}

export async function transferWithWallet({ sender, recipient, amountUnits }, onProgress = () => {}) {
  sender = normalizedAddress(sender);
  recipient = normalizedAddress(recipient);
  if (sender === recipient) throw new Error('Choose a different test wallet as the recipient.');
  if (!Number.isInteger(amountUnits) || amountUnits < 10_000 || amountUnits > 1_000_000 || amountUnits % 10_000) {
    throw new Error('The transfer must be 0.01 to 1 test USDC in steps of 0.01.');
  }
  const wallet = injectedWallet();
  await ensureArc(wallet);
  const accounts = await wallet.request({ method: 'eth_accounts' });
  if (!accounts.some(account => normalizedAddress(account) === sender)) throw new Error('The selected wallet account changed. Connect it again.');
  const incident = await post('/api/wallet/prepare', { sender, recipient, amount_units: amountUnits });
  onProgress({ phase: 'prepared', incident });
  const transaction = validatedTransaction(incident.transaction, { sender, recipient, amountUnits });
  await post(`/api/wallet/${incident.id}/dispatch`, {});
  onProgress({ phase: 'dispatched', incident });
  // If the network changes after the durable dispatch marker, leave an
  // unresolved incident. Never silently open a second signing request.
  if ((await wallet.request({ method: 'eth_chainId' })).toLowerCase() !== arcNetwork.chainId) {
    throw new Error('The wallet network changed after preparation. No automatic retry will be made; review the saved incident.');
  }
  const hash = await wallet.request({ method: 'eth_sendTransaction', params: [transaction] });
  if (!HASH.test(hash)) throw new Error('The wallet did not return a usable hash. The outcome remains unknown; do not send again.');
  // Only public identifiers are saved, so a server interruption need not
  // discard the recovery pointer. No keys or wallet credentials are stored.
  try { localStorage.setItem(`belay-wallet-hash:${incident.id}`, hash); } catch { /* Storage may be disabled. */ }
  onProgress({ phase: 'hash', incident, transactionHash: hash });
  const saved = await attachTransaction(incident.id, hash);
  onProgress({ phase: 'attached', incident: saved, transactionHash: hash });
  return saved;
}

export function mountWallet({ container, config: _config, onIncident = () => {} }) {
  if (!container) return;
  container.innerHTML = `
    <div class="wallet-heading"><div><p class="wallet-eyebrow">PUBLIC TESTNET · NO REAL MONEY</p><h3>Recover a wallet transfer.</h3></div><span class="wallet-tag">Arc Testnet</span></div>
    <p class="wallet-copy">Send up to 1 test USDC between two test wallets. MetaMask asks you to approve. Then inspect the receipt that Belay recovers from the chain.</p>
    <div class="wallet-tools"><button type="button" class="wallet-connect">Connect MetaMask</button><a href="https://faucet.circle.com/" target="_blank" rel="noopener noreferrer">Get free test USDC ↗</a></div>
    <p class="wallet-account" aria-live="polite">Your keys stay in your wallet. Belay does not hold funds.</p>
    <form class="wallet-form">
      <label>Recipient test wallet<input class="wallet-recipient" name="recipient" placeholder="0x…" autocomplete="off" spellcheck="false" required></label>
      <label>Amount in test USDC<input class="wallet-amount" name="amount" type="number" min="0.01" max="1" step="0.01" value="0.10" required></label>
      <button type="submit" class="wallet-send" disabled>Approve a test transfer</button>
    </form>
    <p class="wallet-status" role="status" aria-live="polite">Use a separate test wallet. Circle's faucet supplies tokens for both the transfer and gas on Arc.</p>
    <div class="wallet-recovery" hidden>
      <button type="button" class="wallet-review">Review saved incident</button>
      <p class="wallet-copy">If the browser closed before saving the hash, find the original transaction in MetaMask and attach it here. Attaching a hash only reads evidence.</p>
      <form class="wallet-attach-form"><label>Original transaction hash<input class="wallet-hash" name="hash" placeholder="0x…" autocomplete="off" spellcheck="false" required></label><button type="submit">Attach original hash</button></form>
      <p class="wallet-copy">After this incident is resolved, you can explicitly authorize a new transfer. The original incident stays in your desk.</p>
      <button type="button" class="wallet-new" disabled>Start another test transfer</button>
    </div>
    <details class="wallet-details"><summary>How this demonstration works</summary><p>The transfer is real activity on a public test network; the tokens have no financial value. Belay saves the intent before the wallet opens, then leaves the receipt unrecorded to demonstrate recovery. This deliberate interruption is not a claim that MetaMask crashed. Missing evidence never triggers another transfer.</p><p>Use two test accounts you control. Fund the sender at Circle's faucet: select USDC and Arc Testnet. Leave some test USDC for gas. The wallet signature authorizes this one transfer; it grants Belay no spending allowance.</p></details>`;
  let sender = null;
  let incidentId = null;
  let busy = false;
  let attempted = false;
  let priorStatus = null;
  const query = selector => container.querySelector(selector);
  const status = (message, error = false) => {
    query('.wallet-status').textContent = message;
    query('.wallet-status').dataset.error = String(error);
  };
  const updateButtons = () => {
    query('.wallet-send').disabled = busy || !sender || attempted;
    query('.wallet-connect').disabled = busy || attempted;
    query('.wallet-new').disabled = busy || priorStatus !== 'resolved';
  };
  query('.wallet-connect').addEventListener('click', async () => {
    busy = true; updateButtons();
    try {
      const connected = await connectWallet(); sender = connected.sender;
      query('.wallet-account').textContent = `${sender}${connected.balance !== null ? ' · ' + connected.balance + ' test USDC' : ''}`;
      status('Connected to Arc Testnet. Choose another test account you control as the recipient.');
    } catch (error) { status(error.message, true); }
    finally { busy = false; updateButtons(); }
  });
  query('.wallet-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || attempted || !sender) return;
    busy = true; updateButtons();
    try {
      await transferWithWallet({ sender, recipient: query('.wallet-recipient').value.trim(), amountUnits: parseAmount(query('.wallet-amount').value) }, progress => {
        incidentId = progress.incident.id;
        attempted = true;
        query('.wallet-recovery').hidden = false;
        if (progress.transactionHash) query('.wallet-hash').value = progress.transactionHash;
        status({ prepared: 'Your intent is saved. Preparing the wallet confirmation.', dispatched: 'Review the transfer in MetaMask. This incident will never automatically send again.', hash: `Original transaction: ${progress.transactionHash}. Saving the recovery pointer.`, attached: 'Transaction hash saved; the local receipt is deliberately missing. Open the incident and recover its chain evidence.' }[progress.phase]);
        if (progress.phase === 'prepared' || progress.phase === 'attached') onIncident(incidentId);
      });
    } catch (error) {
      status(`${error.message}${incidentId ? ' The incident is saved. Inspect the original wallet activity; do not send again.' : ''}`, true);
    } finally { busy = false; updateButtons(); }
  });
  query('.wallet-review').addEventListener('click', () => { if (incidentId) onIncident(incidentId); });
  query('.wallet-new').addEventListener('click', async () => {
    if (busy || !incidentId) return;
    busy = true; updateButtons();
    try {
      // This fresh, read-only check is the authority for resetting the form.
      // A cached UI status or button label must never start a second attempt.
      await checkResolvedTransfer(incidentId);
      sender = null; incidentId = null; attempted = false; priorStatus = null;
      query('.wallet-recipient').value = '';
      query('.wallet-amount').value = '0.10';
      query('.wallet-hash').value = '';
      query('.wallet-recovery').hidden = true;
      query('.wallet-account').textContent = 'Your keys stay in your wallet. Belay does not hold funds.';
      status('The resolved incident stays in your desk. Connect a wallet to authorize a new test transfer.');
    } catch (error) { status(error.message, true); }
    finally { busy = false; updateButtons(); }
  });
  query('.wallet-attach-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !incidentId) return;
    busy = true;
    try {
      await attachTransaction(incidentId, query('.wallet-hash').value.trim());
      status('Original hash attached. Review the incident to recover and verify its evidence.');
      onIncident(incidentId);
    } catch (error) { status(error.message, true); }
    finally { busy = false; updateButtons(); }
  });
  return { selectIncident(id) {
    if (!/^[a-f0-9]{32}$/.test(id)) return;
    incidentId = id; attempted = true;
    priorStatus = null;
    query('.wallet-recovery').hidden = false;
    try { query('.wallet-hash').value = localStorage.getItem(`belay-wallet-hash:${id}`) || ''; } catch { /* Optional recovery aid. */ }
    updateButtons();
    checkResolvedTransfer(id).then(incident => {
      if (incidentId === id) { priorStatus = incident.status; updateButtons(); }
    }).catch(() => { /* Unresolved or unavailable means no new transfer. */ });
  }, updateIncident(incident) {
    if (incident?.id === incidentId && incident.provider === 'arc') {
      priorStatus = incident.status;
      updateButtons();
    }
  } };
}
