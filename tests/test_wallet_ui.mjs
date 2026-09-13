import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { beforeEach, test } from 'node:test';

const source = await readFile(new URL('../recovery_app/web/wallet.js', import.meta.url), 'utf8');
const { transferWithWallet, attachTransaction, checkResolvedTransfer, parseAmount } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
);
const sender = '0x' + '1'.repeat(40);
const recipient = '0x' + '2'.repeat(40);
const id = 'a'.repeat(32);
const hash = '0x' + '3'.repeat(64);
const transaction = {
  chainId: '0x4cef52', from: sender,
  to: '0x3600000000000000000000000000000000000000', value: '0x0',
  data: '0xa9059cbb' + recipient.slice(2).padStart(64, '0') + (100000).toString(16).padStart(64, '0'),
};
let calls, mode, stored;
beforeEach(() => {
  calls = []; mode = 'success'; stored = [];
  globalThis.window = { ethereum: { request: async ({method, params}) => {
    calls.push(method);
    if (method === 'eth_chainId') {
      return mode === 'network-change' && calls.includes(`/api/wallet/${id}/dispatch`) ? '0x1' : '0x4cef52';
    }
    if (method === 'eth_accounts') return [mode === 'account-change' ? recipient : sender];
    if (method === 'eth_sendTransaction') {
      assert.deepEqual(params, [transaction]);
      if (mode === 'wallet-rejected') throw new Error('Wallet rejected');
      return mode === 'bad-hash' ? '0x1234' : hash;
    }
    throw new Error('Unexpected wallet method ' + method);
  } } };
  globalThis.localStorage = { setItem: (key, value) => stored.push({key, value}) };
  globalThis.fetch = async (path, options) => {
    calls.push(path);
    if (path === `/api/incidents/${id}`) {
      assert.ok(!options.method || options.method === 'GET');
      assert.equal(options.credentials, 'same-origin');
      return {ok: mode !== 'unavailable', json: async () => ({id, provider: 'arc', status: mode})};
    }
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.equal(options.credentials, 'same-origin');
    if (path.endsWith('/dispatch') && mode === 'dispatch-fail') throw new Error('Transport failed');
    if (path.endsWith('/transaction') && mode === 'attach-fail') throw new Error('Transport failed');
    const result = {id, ...(path.endsWith('/prepare') ? {
      transaction: {...transaction, ...(mode === 'tampered' ? {value: '0x1'} : {})},
    } : {})};
    return {ok: true, json: async () => result};
  };
});

const transfer = progress => transferWithWallet({sender, recipient, amountUnits: 100000}, progress);

test('intent is persisted and dispatch acknowledged before the one wallet call', async () => {
  const phases = [];
  await transfer(progress => phases.push(progress.phase));
  assert.ok(calls.indexOf('/api/wallet/prepare') < calls.indexOf(`/api/wallet/${id}/dispatch`));
  assert.ok(calls.indexOf(`/api/wallet/${id}/dispatch`) < calls.indexOf('eth_sendTransaction'));
  assert.ok(calls.indexOf('eth_sendTransaction') < calls.indexOf(`/api/wallet/${id}/transaction`));
  assert.equal(calls.filter(call => call === 'eth_sendTransaction').length, 1);
  assert.deepEqual(phases, ['prepared', 'dispatched', 'hash', 'attached']);
});

for (const failure of ['dispatch-fail', 'tampered', 'network-change', 'account-change']) {
  test(`${failure} prevents a wallet send`, async () => {
    mode = failure;
    await assert.rejects(transfer());
    assert.ok(!calls.includes('eth_sendTransaction'));
  });
}

for (const failure of ['wallet-rejected', 'bad-hash']) {
  test(`${failure} never retries or attaches an invented hash`, async () => {
    mode = failure;
    await assert.rejects(transfer());
    assert.equal(calls.filter(call => call === 'eth_sendTransaction').length, 1);
    assert.ok(!calls.includes(`/api/wallet/${id}/transaction`));
  });
}

test('a hash is retained as a public recovery pointer when server attachment fails', async () => {
  mode = 'attach-fail';
  await assert.rejects(transfer());
  assert.equal(calls.filter(call => call === 'eth_sendTransaction').length, 1);
  assert.deepEqual(stored, [{key: `belay-wallet-hash:${id}`, value: hash}]);
});

test('manual hash attachment never accesses the wallet or sends a transaction', async () => {
  await attachTransaction(id, hash);
  assert.deepEqual(calls, [`/api/wallet/${id}/transaction`]);
});

test('invalid attachment identifiers are rejected without network activity', async () => {
  await assert.rejects(attachTransaction('../other', hash));
  await assert.rejects(attachTransaction(id, '0x1234'));
  assert.deepEqual(calls, []);
});

test('starting another transfer requires a fresh read of a resolved wallet incident', async () => {
  mode = 'resolved';
  const previous = await checkResolvedTransfer(id);
  assert.equal(previous.id, id);
  assert.equal(previous.status, 'resolved');
  assert.deepEqual(calls, [`/api/incidents/${id}`]);
});

test('unresolved, failed or unavailable incidents cannot unlock another transfer', async () => {
  for (const status of ['prepared', 'unresolved', 'needs_evidence', 'ready', 'failed', 'unavailable']) {
    mode = status;
    await assert.rejects(checkResolvedTransfer(id));
  }
  assert.ok(calls.every(call => call === `/api/incidents/${id}`));
});

test('amount parser permits exact cents and enforces the one-test-USDC cap', () => {
  assert.equal(parseAmount('0.01'), 10000);
  assert.equal(parseAmount('0.10'), 100000);
  assert.equal(parseAmount('1.00'), 1000000);
  for (const amount of ['0', '0.001', '1.01', '0x1', '1e0', '', -1]) {
    assert.throws(() => parseAmount(amount));
  }
});

test('invalid amount and recipient never reach the server or wallet', async () => {
  await assert.rejects(transferWithWallet({sender, recipient, amountUnits: 10001}));
  await assert.rejects(transferWithWallet({sender, recipient: sender, amountUnits: 100000}));
  await assert.rejects(transferWithWallet({sender, recipient: '0x' + '0'.repeat(40), amountUnits: 100000}));
  assert.deepEqual(calls, []);
});
