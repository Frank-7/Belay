"""The real-wallet path must fail closed across RPC and identity ambiguity."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recovery_app.arc import (  # noqa: E402
    CHAIN_HEX,
    CHAIN_ID,
    TOKEN_ADDRESS,
    TRANSFER_TOPIC,
    ArcEvidenceProvider,
    prepare_transaction,
    read_rpc,
)

SENDER = "0x" + "1" * 40
RECIPIENT = "0x" + "2" * 40
TX_HASH = "0x" + "3" * 64
BLOCK_HASH = "0x" + "4" * 64
FINAL_HASH = "0x" + "5" * 64


def evidence():
    unsigned = prepare_transaction(SENDER, RECIPIENT, 100_000)
    tx = {
        "hash": TX_HASH, "from": SENDER, "to": TOKEN_ADDRESS,
        "chainId": CHAIN_HEX, "input": unsigned["data"], "value": "0x0",
        "blockNumber": "0x65", "blockHash": BLOCK_HASH,
    }
    log = {
        "address": TOKEN_ADDRESS,
        "topics": [TRANSFER_TOPIC, "0x" + SENDER[2:].zfill(64), "0x" + RECIPIENT[2:].zfill(64)],
        "data": f"0x{100_000:064x}", "removed": False,
        "transactionHash": TX_HASH, "blockNumber": "0x65", "blockHash": BLOCK_HASH,
    }
    receipt = {
        "transactionHash": TX_HASH, "from": SENDER, "to": TOKEN_ADDRESS,
        "blockNumber": "0x65", "blockHash": BLOCK_HASH,
        "status": "0x1", "logs": [log],
    }
    return {
        "chain": CHAIN_HEX, "transaction": tx, "receipt": receipt,
        "finalized": {"number": "0x66", "hash": FINAL_HASH},
        "canonical": {"number": "0x65", "hash": BLOCK_HASH},
    }


class ArcTests(unittest.TestCase):
    def setUp(self):
        self.data = evidence()
        self.calls = []
        self.expected = {
            "sender": SENDER, "recipient": RECIPIENT, "amount_units": 100_000,
            "transaction_hash": TX_HASH, "min_block_number": 100,
        }
        self.provider = ArcEvidenceProvider(self.rpc)

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return self.data["chain"]
        if method == "eth_getTransactionByHash":
            self.assertEqual(params, [TX_HASH])
            return self.data["transaction"]
        if method == "eth_getTransactionReceipt":
            self.assertEqual(params, [TX_HASH])
            return self.data["receipt"]
        if method == "eth_getBlockByNumber":
            if params[0] in ("finalized", "latest"):
                return self.data["finalized"]
            self.assertEqual(params, ["0x65", False])
            return self.data["canonical"]
        self.fail(f"Unexpected method, especially a write: {method}")

    def assert_unknown(self):
        result = self.provider.read(self.expected)
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(result["records"], [])
        return result

    def test_success_is_bound_to_exact_finalized_transfer(self):
        result = self.provider.read(self.expected)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["records"][0]["external_id"], TX_HASH)
        self.assertEqual(result["records"][0]["amount_units"], 100_000)
        self.assertEqual(result["metadata"]["finality"], "canonical finalized block")
        self.assertIn(("eth_getBlockByNumber", ["finalized", False]), self.calls)
        self.assertFalse(any(method.startswith("eth_send") for method, _ in self.calls))

    def test_no_hash_is_unknown_without_rpc(self):
        self.expected["transaction_hash"] = None
        self.assert_unknown()
        self.assertEqual(self.calls, [])

    def test_missing_transaction_or_receipt_does_not_prove_absence(self):
        for missing in ("transaction", "receipt"):
            with self.subTest(missing=missing):
                self.data = evidence()
                self.data[missing] = None
                self.assert_unknown()

    def test_wrong_network_is_rejected_before_transaction_lookup(self):
        self.data["chain"] = "0x1"
        self.assert_unknown()
        self.assertEqual(self.calls, [("eth_chainId", [])])

    def test_every_intent_field_is_checked(self):
        mutations = {
            "from": RECIPIENT, "to": RECIPIENT, "chainId": "0x1",
            "value": "0x1", "input": prepare_transaction(SENDER, RECIPIENT, 200_000)["data"],
            "hash": FINAL_HASH,
        }
        for key, value in mutations.items():
            with self.subTest(field=key):
                self.data = evidence()
                self.data["transaction"][key] = value
                self.assert_unknown()

    def test_receipt_identity_fields_are_checked(self):
        for key, value in {"from": RECIPIENT, "to": RECIPIENT, "transactionHash": FINAL_HASH,
                           "blockHash": FINAL_HASH, "blockNumber": "0x66"}.items():
            with self.subTest(field=key):
                self.data = evidence()
                self.data["receipt"][key] = value
                self.assert_unknown()

    def test_old_payment_cannot_satisfy_new_intent(self):
        self.expected["min_block_number"] = 101
        self.assert_unknown()
        self.assertFalse(any(method == "eth_getBlockByNumber" for method, _ in self.calls))

    def test_finality_and_canonical_block_are_required(self):
        for change in ("unavailable", "not_final", "canonical_mismatch", "same_height_mismatch"):
            with self.subTest(change=change):
                self.data = evidence()
                if change == "unavailable":
                    self.data["finalized"] = None
                elif change == "not_final":
                    self.data["finalized"]["number"] = "0x64"
                elif change == "canonical_mismatch":
                    self.data["canonical"]["hash"] = FINAL_HASH
                else:
                    self.data["finalized"]["number"] = "0x65"
                self.assert_unknown()

    def test_revert_is_failed_only_after_finalized_identity_checks(self):
        self.data["receipt"].update(status="0x0", logs=[])
        result = self.provider.read(self.expected)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["records"], [])
        self.data["finalized"] = None
        self.assert_unknown()

    def test_no_event_or_duplicate_event_cannot_confirm_payment(self):
        log = copy.deepcopy(self.data["receipt"]["logs"][0])
        for logs in ([], [log, log]):
            with self.subTest(count=len(logs)):
                self.data["receipt"]["logs"] = logs
                self.assert_unknown()

    def test_transfer_event_must_match_receipt_and_intent(self):
        mutations = {
            "data": f"0x{200_000:064x}", "removed": True,
            "address": RECIPIENT, "transactionHash": FINAL_HASH,
            "blockHash": FINAL_HASH, "blockNumber": "0x64",
            "topics": [TRANSFER_TOPIC, "0x" + RECIPIENT[2:].zfill(64), "0x" + SENDER[2:].zfill(64)],
        }
        for key, value in mutations.items():
            with self.subTest(field=key):
                self.data = evidence()
                self.data["receipt"]["logs"][0][key] = value
                self.assert_unknown()

    def test_rpc_transport_failure_and_malformed_evidence_are_unknown(self):
        def offline(method, params):
            raise OSError("offline")
        self.provider = ArcEvidenceProvider(offline)
        self.assert_unknown()
        self.provider = ArcEvidenceProvider(self.rpc)
        for bad in ([], True, {"status": "0x1"}):
            with self.subTest(receipt=bad):
                self.data["receipt"] = bad
                self.assert_unknown()

    def test_prepare_rejects_money_boundaries_and_self_transfers(self):
        for units in (True, "100000", 0, 9999, 10001, 1_000_001):
            with self.subTest(units=units), self.assertRaises(ValueError):
                prepare_transaction(SENDER, RECIPIENT, units)
        with self.assertRaises(ValueError):
            prepare_transaction(SENDER, SENDER, 100_000)
        with self.assertRaises(ValueError):
            prepare_transaction(SENDER, "0x" + "0" * 40, 100_000)
        self.assertEqual(prepare_transaction(SENDER, RECIPIENT, 1_000_000)["chainId"], CHAIN_HEX)

    def test_bad_prepared_boundary_rejected(self):
        for boundary in (-1, True, "100"):
            with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                self.provider.read({**self.expected, "min_block_number": boundary})

    def test_head_checks_network_and_block_shape(self):
        result = self.provider.head()
        self.assertEqual(result["chain_id"], CHAIN_ID)
        self.assertEqual(result["block_number"], 102)
        self.data["chain"] = "0x1"
        with self.assertRaises(ValueError):
            self.provider.head()

    def test_rpc_writer_methods_are_never_allowed(self):
        for method in ("eth_sendTransaction", "eth_sendRawTransaction", "personal_sign"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                read_rpc(method, [])


if __name__ == "__main__":
    unittest.main()
