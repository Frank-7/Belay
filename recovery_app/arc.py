"""Read-only, intent-bound evidence from Circle USDC on Arc Testnet.

Wallet signing belongs to the person using MetaMask. This module has no key,
signing, broadcast, allowance, or retry operation. A missing receipt never
proves that a transfer did not happen. RPC responses are evidence under the
selected node and Arc consensus assumptions, not a light-client proof.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

CHAIN_ID = 5042002
CHAIN_HEX = "0x4cef52"
RPC_URL = "https://rpc.testnet.arc.io"
EXPLORER_URL = "https://testnet.arcscan.app"
TOKEN_ADDRESS = "0x3600000000000000000000000000000000000000"
TOKEN_DECIMALS = 6
MAX_AMOUNT_UNITS = 1_000_000
TRANSFER_SELECTOR = "a9059cbb"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")
_QUANTITY = re.compile(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)\Z")
_READ_METHODS = frozenset({
    "eth_chainId", "eth_getTransactionByHash", "eth_getTransactionReceipt",
    "eth_getBlockByNumber", "eth_call", "eth_getBalance",
})


def address(value: Any) -> str:
    """Normalize a public address; zero is never a valid demo participant."""
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise ValueError("Use a complete 0x-prefixed wallet address")
    if int(value, 16) == 0:
        raise ValueError("The zero address cannot receive this demo transfer")
    return value.lower()


def transaction_hash(value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Use a complete 0x-prefixed transaction hash")
    return value.lower()


def amount_units(value: Any) -> int:
    if (type(value) is not int or not 10_000 <= value <= MAX_AMOUNT_UNITS
            or value % 10_000 != 0):
        raise ValueError("Transfer between 0.01 and 1 test USDC in steps of 0.01")
    return value


def transfer_data(recipient: str, units: int) -> str:
    return "0x" + TRANSFER_SELECTOR + address(recipient)[2:].zfill(64) + f"{amount_units(units):064x}"


def prepare_transaction(sender: str, recipient: str, units: int) -> dict:
    """Unsigned, fixed-network transaction. Call only after persisting intent."""
    sender, recipient = address(sender), address(recipient)
    if sender == recipient:
        raise ValueError("Use a different test wallet as the recipient")
    return {
        "chainId": CHAIN_HEX,
        "from": sender,
        "to": TOKEN_ADDRESS,
        "value": "0x0",
        "data": transfer_data(recipient, units),
    }


def network_config() -> dict:
    return {
        "chain_id": CHAIN_ID, "chain_hex": CHAIN_HEX,
        "name": "Arc Testnet", "rpc_url": RPC_URL,
        "explorer_url": EXPLORER_URL, "token_address": TOKEN_ADDRESS,
        "decimals": TOKEN_DECIMALS, "max_amount_units": MAX_AMOUNT_UNITS,
        "min_amount_units": 10_000, "step_amount_units": 10_000,
        "faucet_url": "https://faucet.circle.com/", "asset": "test USDC",
    }


def _quantity(value: Any) -> int:
    if not isinstance(value, str) or not _QUANTITY.fullmatch(value):
        raise ValueError("Invalid RPC quantity")
    return int(value, 16)


def _hash(value: Any) -> str:
    return transaction_hash(value)


def read_rpc(method: str, params: list) -> Any:
    """Fixed endpoint and read-only method allowlist; never broadcasts."""
    if method not in _READ_METHODS:
        raise ValueError("Only read-only Arc RPC methods are supported")
    request = urllib.request.Request(
        RPC_URL,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Belay-Recovery-ReadOnly/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        if response.geturl() != RPC_URL:
            raise ValueError("The configured Arc RPC endpoint redirected")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Arc RPC response exceeded the evidence size limit")
    document = json.loads(raw)
    if (not isinstance(document, dict) or document.get("jsonrpc") != "2.0"
            or type(document.get("id")) is not int or document["id"] != 1
            or "error" in document or "result" not in document):
        raise ValueError("Arc RPC did not return a usable response")
    return document["result"]


class ArcEvidenceProvider:
    """Verify one previously authorized transfer without sending anything.

    ``rpc`` is dependency injection for offline tests. Application callers use
    the fixed public endpoint. The caller owns durable intent, single-dispatch
    rules, and transaction-hash uniqueness across incidents.
    """

    def __init__(self, rpc=None):
        self.rpc = rpc or read_rpc

    def head(self) -> dict:
        """Capture a public chain boundary before the caller saves intent."""
        if _quantity(self.rpc("eth_chainId", [])) != CHAIN_ID:
            raise ValueError("The evidence endpoint is not Arc Testnet")
        block = self.rpc("eth_getBlockByNumber", ["latest", False])
        if not isinstance(block, dict):
            raise ValueError("Arc block boundary is unavailable")
        return {"block_number": _quantity(block.get("number")),
                "block_hash": _hash(block.get("hash")), "chain_id": CHAIN_ID}

    def read(self, expected: dict) -> dict:
        sender = address(expected.get("sender"))
        recipient = address(expected.get("recipient"))
        units = amount_units(expected.get("amount_units"))
        if sender == recipient:
            raise ValueError("Sender and recipient must be different test wallets")
        min_block = expected.get("min_block_number")
        if min_block is not None and (type(min_block) is not int or min_block < 0):
            raise ValueError("The prepared block boundary must be a nonnegative integer")
        tx_hash = expected.get("transaction_hash")
        if tx_hash is not None and tx_hash != "":
            tx_hash = transaction_hash(tx_hash)
        metadata = {
            "chain_id": CHAIN_ID, "token_address": TOKEN_ADDRESS,
            "asset": "test USDC", "decimals": TOKEN_DECIMALS,
            "explorer_url": f"{EXPLORER_URL}/tx/{tx_hash}" if tx_hash else None,
            "transaction_hash": tx_hash or None,
            "rpc_url": RPC_URL, "finality": "not established",
            "trust": "Configured public RPC and Arc consensus; not a light-client proof",
        }
        raw = {}

        def result(status: str, reason: str, records=None) -> dict:
            return {"status": status, "reason": reason, "records": records or [],
                    "metadata": metadata, "raw": raw}

        if not tx_hash:
            return result("unknown", "The wallet may have sent the transfer, but its transaction hash is missing. Attach the original hash; do not send again.")
        try:
            if _quantity(self.rpc("eth_chainId", [])) != CHAIN_ID:
                return result("unknown", "The evidence endpoint is not Arc Testnet.")
            tx = self.rpc("eth_getTransactionByHash", [tx_hash])
            receipt = self.rpc("eth_getTransactionReceipt", [tx_hash])
            raw.update(transaction=tx, receipt=receipt)
            if tx is None or receipt is None:
                return result("unknown", "No complete transaction receipt is available. Pending, dropped, and unavailable evidence cannot establish absence.")
            if not isinstance(tx, dict) or not isinstance(receipt, dict):
                raise ValueError("Invalid transaction or receipt shape")
            expected_data = transfer_data(recipient, units)
            if (_hash(tx.get("hash")) != tx_hash
                    or _hash(receipt.get("transactionHash")) != tx_hash
                    or address(tx.get("from")) != sender
                    or address(receipt.get("from")) != sender
                    or address(tx.get("to")) != TOKEN_ADDRESS
                    or address(receipt.get("to")) != TOKEN_ADDRESS
                    or _quantity(tx.get("chainId")) != CHAIN_ID
                    or _quantity(tx.get("value")) != 0
                    or not isinstance(tx.get("input"), str)
                    or tx["input"].lower() != expected_data):
                return result("unknown", "The transaction does not exactly match the saved sender, recipient, token, network, and amount.")
            number = _quantity(receipt.get("blockNumber"))
            if min_block is not None and number <= min_block:
                return result("unknown", "The transaction predates this saved intent's block boundary. An earlier payment cannot settle this incident.")
            block_hash = _hash(receipt.get("blockHash"))
            if (_quantity(tx.get("blockNumber")) != number
                    or _hash(tx.get("blockHash")) != block_hash):
                return result("unknown", "Transaction and receipt disagree about block inclusion.")
            finalized = self.rpc("eth_getBlockByNumber", ["finalized", False])
            canonical = self.rpc("eth_getBlockByNumber", [hex(number), False])
            raw.update(finalized_block=finalized, canonical_block=canonical)
            if not isinstance(finalized, dict) or not isinstance(canonical, dict):
                return result("unknown", "Finalized and canonical block evidence is unavailable; latest-block inclusion is insufficient.")
            finalized_number = _quantity(finalized.get("number"))
            finalized_hash = _hash(finalized.get("hash"))
            if (number > finalized_number
                    or _quantity(canonical.get("number")) != number
                    or _hash(canonical.get("hash")) != block_hash
                    or (number == finalized_number and finalized_hash != block_hash)):
                return result("unknown", "The receipt is not established in the canonical finalized chain.")
            metadata.update(block_number=number, block_hash=block_hash,
                            finalized_block_number=finalized_number,
                            finality="canonical finalized block")
            status = _quantity(receipt.get("status"))
            if status == 0:
                return result("failed", "The exact transaction finalized but execution reverted. No successful transfer is established; test gas may have been spent. A new transfer requires a new explicit authorization.")
            if status != 1:
                raise ValueError("Invalid receipt status")
            logs = receipt.get("logs")
            if not isinstance(logs, list):
                raise ValueError("Missing receipt logs")
            matches = []
            for log in logs:
                if not isinstance(log, dict):
                    raise ValueError("Invalid receipt log")
                if str(log.get("address", "")).lower() != TOKEN_ADDRESS:
                    continue
                topics = log.get("topics")
                if not isinstance(topics, list) or not topics or str(topics[0]).lower() != TRANSFER_TOPIC:
                    continue
                # Every transfer emitted by this direct token call must agree
                # with its durable intent. Do not select a convenient log while
                # ignoring an inconsistent or duplicate token movement.
                if (len(topics) != 3
                        or [str(value).lower() for value in topics[1:]] != ["0x" + sender[2:].zfill(64), "0x" + recipient[2:].zfill(64)]
                        or not isinstance(log.get("data"), str)
                        or log["data"].lower() != f"0x{units:064x}"
                        or log.get("removed", False) is not False
                        or _hash(log.get("transactionHash")) != tx_hash
                        or _hash(log.get("blockHash")) != block_hash
                        or _quantity(log.get("blockNumber")) != number):
                    return result("unknown", "The token transfer event does not match the saved intent and finalized receipt.")
                matches.append(log)
            if len(matches) != 1:
                return result("unknown", "Exactly one matching Circle test-USDC Transfer event is required.")
            record = {
                "external_id": tx_hash, "transaction_hash": tx_hash,
                "sender": sender, "recipient": recipient, "amount_units": units,
                "token_address": TOKEN_ADDRESS, "chain_id": CHAIN_ID,
                "block_number": number, "block_hash": block_hash,
            }
            return result("committed", "The original transfer matches the saved intent and has one successful token event in a canonical finalized block. No replacement transfer was sent.", [record])
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return result("unknown", "Arc evidence is unavailable or malformed. Keep the original intent and transaction hash; do not send again.")
