# A real testnet transfer, with no real money

Belay can recover evidence for a **Circle test-USDC transfer on Arc Testnet**.
MetaMask signs the transfer in the user's browser. Belay does not create a
custodial wallet, hold funds, receive a recovery phrase, or get a spending
allowance. The AI proposes how to interpret evidence; it cannot sign or send.

This is an addition to the local simulated incidents. The simulated provider
does not become a blockchain when this option is enabled. The UI labels which
provider produced each incident.

## What is free, and what needs your participation?

Arc Testnet transactions spend test USDC for both the transfer and gas. Circle's
public faucet currently provides 20 test USDC per address and network every two
hours. These tokens have **no financial value and are not backed by dollars**.
No purchase, bridge, mainnet balance, paid RPC key, or contract deployment is
required by this integration. Faucet availability and rate limits are external
to Belay. [Circle faucet][1] · [Circle test-token definitions][2]

You install/unlock MetaMask and approve its own wallet prompts. Belay cannot do
those steps on your behalf. Use a separate test wallet and two accounts you
control. Never enter a secret recovery phrase or private key into Belay.

The public blockchain activity is real; the money is not. This implementation
has not established a production custody, guarantee, escrow, or insurance
service. It does not give an agent unrestricted access to a wallet.

## Setup

1. Install MetaMask from its [official website][3] if necessary. Create a
   separate wallet for testing, or select a dedicated test account. Create a
   second test account to receive the transfer. Keep the recovery phrase inside
   your own wallet setup and backup process.
2. Start the local application from the repository:

   ```sh
   python -m recovery_app.server --port 8766
   ```

   Open `http://127.0.0.1:8766` in the browser where MetaMask is installed. The
   local app is required: GitHub Pages cannot run this Python recovery service.
3. Open the wallet section and choose **Connect MetaMask**. Approve connecting
   the sender account and adding/switching to **Arc Testnet**. Belay asks for
   account access, not a token allowance.
4. Open [Circle's faucet][1], choose **USDC**, choose **Arc Testnet**, and paste
   the sender's public address. Request the free tokens. Do not purchase tokens
   if a faucet is temporarily unavailable.
5. Connect again to refresh the displayed balance. Enter the second account's
   public address as recipient and start with **0.10 test USDC**. Leave test USDC
   in the sender to cover gas. Belay permits 0.01–1.00 test USDC per transfer, in
   increments of 0.01.

Arc's official manual network settings are:

| Setting | Value |
|---|---|
| Name | Arc Testnet |
| Chain ID | `5042002` (`0x4cef52`) |
| RPC | `https://rpc.testnet.arc.io` |
| Native currency | USDC, 18 decimals |
| Explorer | `https://testnet.arcscan.app` |
| Circle USDC ERC-20 interface | `0x3600000000000000000000000000000000000000` |
| ERC-20 decimals | 6 |

The native and ERC-20 interfaces share **one balance**. Do not add their balances
together. Belay sends through the six-decimal ERC-20 interface and attaches no
native value to that call; Arc charges gas separately from the same underlying
balance. [Arc wallet connection][4] · [Arc EVM differences][5]

## Record the demonstration

1. **Show the request.** The operator authorizes a 0.10 test-USDC transfer to the
   chosen second test wallet.
2. **Save intent before signing.** Belay captures the current chain boundary,
   persists the sender, recipient, token, amount and chain, then records that a
   wallet request is about to start. Only then does MetaMask open a transaction
   confirmation.
3. **Approve in MetaMask.** Verify Arc Testnet, the selected account and transfer.
   MetaMask submits the signed transaction and returns its hash. The app saves
   that hash and deliberately leaves the local receipt unacknowledged. Say:
   “The transfer is on the public test network; we deliberately stopped the app
   from recording its receipt so we can demonstrate recovery.” Do not claim the
   wallet or machine actually crashed in this step.
4. **Investigate the incident.** Belay reads the original transaction and
   receipt. It checks the saved intent and finalized chain evidence. The same
   application evidence flow then produces a proposed recovery resolution.
5. **Inspect before resolving.** Show the exact amount and recipient, the
   transaction hash, the finalized block and the explorer link. A successful
   recovery records the original transfer; it does not send a second one.
6. **Export the receipt.** The application audit record includes the public
   provider evidence and the resolution. It is an inspectable record, not a
   cryptographic attestation of independent external truth.
7. **Repeat deliberately.** After the incident is resolved, choose **Start
   another test transfer**. Belay checks the prior resolution again before
   clearing the form. The old incident remains in the desk; connecting and
   signing again creates a new authorized transfer, never a retry of the old
   incident.

MetaMask's `eth_sendTransaction` returns the transaction hash after a user
confirmation. It does not let Belay retrieve a key. [MetaMask transaction API][6]

## If anything is interrupted

**There is no automatic second transfer.** A missing receipt can mean pending,
dropped, unavailable, or incompletely observed activity. A missing hash is also
unknown: the browser can disappear after the wallet sent a transaction but
before the application saved its hash.

Select the saved wallet incident. In MetaMask's original activity, find the
transaction hash and use **Attach original hash**. This is a read-only recovery
pointer. Belay checks the sender, recipient, token, amount and block boundary;
a hash for a different tuple or an older transfer cannot satisfy the intent.
Always attach the original transaction from that wallet request. Do not attach
another transfer merely because its amount looks the same.

The browser stores only a public hash under a per-incident local-storage key as
an optional recovery aid. The application journal holds the durable intent and
dispatch marker. A saved incident is never automatically sent again after a
reload. If the wallet prompt was rejected, the conservative outcome is still
an unresolved incident until the operator reviews it; Belay does not turn an
exception into permission to create another transfer.

Revoking permission in Belay stops a new wallet-dispatch request. It cannot
cancel a MetaMask confirmation that is already open, or undo a signed transfer.
Reject an outstanding prompt inside MetaMask itself. A later wallet signature
is a direct user authorization, not an autonomous Belay action.

An exact transaction that finalized with `status: 0` is reported as failed:
execution reverted, although test gas may have been consumed. Choose **Record
failure without sending** to close that investigation. Belay rechecks the exact
receipt and canonical finality before recording a durable failed outcome; it
does not classify the request as absent or call a payment provider. The receipt
keeps the transaction hash, original chain evidence, and gas disclosure.
[Arc transaction lifecycle][7]

Here, a `resolved` incident means its investigation is closed. Its payment
outcome is still `failed`, and the UI says **Failed transaction recorded**.
After closure, **Start another test transfer** resets the form only after a
fresh server check. A new intent and another explicit MetaMask signature are
required, even when sender, recipient and amount are unchanged. A missing,
unfinalized or unavailable receipt keeps the old incident unresolved and does
not unlock another identical request. Restarting the app or submitting the
same closure twice never repeats the transfer.

## What the verifier checks

`recovery_app/arc.py` permits only read-only RPC methods at a fixed Arc Testnet
endpoint. It never signs, broadcasts, changes a nonce, grants an allowance, or
accepts a user-supplied RPC URL. The verifier requires:

- Arc Testnet chain identity, exact sender and Circle token address, zero native
  value, and exact `transfer(recipient, amount)` calldata.
- Matching transaction hashes and block identity in the transaction and receipt.
- A receipt block strictly later than the boundary captured when the incident
  was prepared, excluding older transactions from satisfying new intent.
- An explicit `finalized` head and a matching canonical block; merely appearing
  in `latest` is insufficient. Unsupported or malformed finality evidence stays
  unknown.
- Successful execution and exactly one matching ERC-20 `Transfer` log, including
  matching sender, recipient, amount, transaction and block. Removed, inconsistent
  or duplicate token-transfer logs do not confirm the payment.

The application separately enforces one wallet-dispatch request per incident
and prevents assigning a transaction hash to multiple incidents. The chain does
not know Belay's order or authorization. Belay binds the independently checked
transaction tuple to its own saved intent; it never trusts an order identity
invented by a model or returned by a wallet UI.

**Identity boundary:** two transfers between the same accounts for the same
amount are not distinguishable by those fields alone. Belay rejects simultaneous
unresolved wallet incidents with an identical sender, recipient and amount.
This reduces accidental cross-assignment inside the app; it cannot prevent an
unrelated matching transfer made outside Belay. The demo therefore assumes the
operator attaches the original hash. It does not claim a cryptographic link
between a Belay order ID and an ERC-20 transfer, and it does not reserve or bind
a wallet nonce. Stronger attribution would require an additional signing or
on-chain correlation design.

These checks trust the configured public RPC's chain responses and Arc's
consensus assumptions. Belay is not running a light client, verifying validator
signatures, or proving the receipt against a separately trusted block header.
Arc documents finality on block inclusion; this implementation also demands
the explicit finalized/canonical responses to fail closed if that evidence is
unavailable. [Arc finality behavior][7]

## Verification and remaining live setup

Run the offline regression tests without a wallet, network, or money:

```sh
python -m unittest tests.test_arc -v
node --test tests/test_wallet_ui.mjs
```

They cover exact-intent validation, wrong networks, stale transactions, missing
hashes and receipts, inconsistent or unfinalized blocks, reverted execution,
bad/duplicate token events, transport errors, and amount boundaries. The RPC
adapter rejects broadcast/signing methods before any network call.
The wallet-helper tests check durable ordering, account/network changes,
transaction tampering, rejected prompts, invalid hashes, attachment failures,
and the absence of automatic retries. A browser regression with an injected
mock wallet also exercised the real local server, Arc adapter, shared
adjudicator and resolution flow, including a reload with no second send.

Read-only network configuration was checked on 2026-09-13: the public endpoint
returned chain `0x4cef52`, valid `finalized` and `safe` block responses, and six
decimals for the fixed Circle token. This is **not** an assertion that an actual
wallet transfer was executed. A complete public-transfer demonstration still
requires the user's wallet connection, faucet claim and signature, followed by
inspection of the resulting transaction and recovered receipt.

The local simulated incidents remain available when MetaMask or the faucet is
unavailable. Label that fallback as a simulation rather than presenting it as
an on-chain transfer.

## Primary sources

Configuration and prerequisites checked 2026-09-13. External faucet limits and
testnet infrastructure can change.

[1]: https://faucet.circle.com/
[2]: https://developers.circle.com/stablecoins/usdc-contract-addresses
[3]: https://metamask.io/
[4]: https://docs.arc.io/integrate/connect-to-arc
[5]: https://docs.arc.io/integrate/evm-differences
[6]: https://docs.metamask.io/metamask-connect/evm/reference/json-rpc-api/eth_sendTransaction/
[7]: https://docs.arc.io/integrate/wallets/transaction-lifecycle

- [Circle testnet faucet][1]
- [Circle USDC token addresses and test-token definition][2]
- [MetaMask official website][3]
- [Arc connection and wallet setup][4]
- [Arc native/ERC-20 interface differences][5]
- [MetaMask `eth_sendTransaction`][6]
- [Arc pending/finalized/reverted transaction lifecycle][7]
