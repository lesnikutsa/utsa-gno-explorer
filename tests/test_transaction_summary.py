import json
import unittest

from indexer.transaction_summary import (
    MAX_LABEL_LENGTH,
    MAX_MESSAGES,
    MAX_TYPE_LENGTH,
    generic_summary,
    normalize_summary,
)


class TransactionSummaryTests(unittest.TestCase):
    def test_generic_decoded_and_invalid_fallbacks(self):
        decoded = generic_summary()
        self.assertEqual(decoded["schema_version"], 1)
        self.assertEqual(decoded["chain_family"], "unknown")
        self.assertEqual(decoded["parse_status"], "unparsed")
        self.assertIsNone(decoded["message_count"])
        self.assertFalse(decoded["messages_truncated"])
        self.assertEqual(decoded["primary"]["label"], "Transaction")
        self.assertEqual(decoded["messages"], [])

        raw_base64 = "c2Vuc2l0aXZlLXJhdy10cmFuc2FjdGlvbg=="
        invalid = generic_summary("invalid")
        self.assertEqual(invalid["parse_status"], "invalid")
        self.assertNotIn(raw_base64, json.dumps(invalid))

    def test_summary_is_json_safe_and_contains_no_bytes(self):
        summary = generic_summary()
        json.dumps(summary)

        def assert_no_bytes(value):
            self.assertNotIsInstance(value, bytes)
            if isinstance(value, dict):
                for nested in value.values():
                    assert_no_bytes(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_no_bytes(nested)

        assert_no_bytes(summary)

    def test_adapter_summary_is_bounded(self):
        candidate = generic_summary("parsed")
        candidate["primary"] = {
            "type": "t" * (MAX_TYPE_LENGTH + 50),
            "category": "transfer",
            "action": "send",
            "label": "l" * (MAX_LABEL_LENGTH + 50),
        }
        candidate["message_count"] = MAX_MESSAGES + 5
        candidate["messages"] = [{"type": "m" * 500, "label": "x" * 500} for _ in range(MAX_MESSAGES + 5)]
        summary = normalize_summary(candidate)
        self.assertEqual(len(summary["messages"]), MAX_MESSAGES)
        self.assertTrue(summary["messages_truncated"])
        self.assertEqual(len(summary["primary"]["type"]), MAX_TYPE_LENGTH)
        self.assertEqual(len(summary["primary"]["label"]), MAX_LABEL_LENGTH)
        self.assertEqual(len(summary["messages"][0]["type"]), MAX_TYPE_LENGTH)

    def test_malformed_or_sensitive_adapter_output_falls_back(self):
        malformed = normalize_summary({"messages": [{"raw_base64": b"payload"}]})
        self.assertEqual(malformed, generic_summary())

        sensitive = generic_summary("parsed")
        sensitive["messages"] = [{"signature": "must-not-be-stored"}]
        self.assertEqual(normalize_summary(sensitive), generic_summary())

    def test_generic_contract_is_chain_neutral(self):
        serialized = json.dumps(generic_summary()).lower()
        for network_field in ("package_path", "function_name", "gpub", "type_url", "denom", "valoper", "ibc_channel", "proposal_id"):
            self.assertNotIn(network_field, serialized)


if __name__ == "__main__":
    unittest.main()
