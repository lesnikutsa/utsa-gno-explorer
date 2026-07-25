import json
import unittest

from api.app import _public_transaction_summary
from indexer.transaction_summary import (
    MAX_LABEL_LENGTH,
    MAX_INTEGER_BITS,
    MAX_MESSAGE_COUNT,
    MAX_MESSAGES,
    MAX_SUMMARY_BYTES,
    MAX_TOKEN_LENGTH,
    MAX_TYPE_LENGTH,
    generic_summary,
    normalize_summary,
    summary_size_bytes,
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

    def test_total_compact_utf8_size_removes_trailing_messages(self):
        candidate = generic_summary("parsed")
        candidate["message_count"] = MAX_MESSAGES
        candidate["messages"] = [
            {f"field_{field}": "界" * 160 for field in range(16)}
            for _ in range(MAX_MESSAGES)
        ]

        summary = normalize_summary(candidate)

        self.assertLess(len(summary["messages"]), MAX_MESSAGES)
        self.assertTrue(summary["messages_truncated"])
        self.assertLessEqual(summary_size_bytes(summary), MAX_SUMMARY_BYTES)
        self.assertGreater(len(json.dumps(summary, ensure_ascii=False)), 0)

    def test_message_count_controls_consistency_and_truncation(self):
        omitted = generic_summary("parsed")
        omitted["message_count"] = 25
        omitted["messages"] = [{"type": "message"} for _ in range(MAX_MESSAGES)]
        self.assertTrue(normalize_summary(omitted)["messages_truncated"])

        impossible = generic_summary("parsed")
        impossible["message_count"] = 1
        impossible["messages"] = [{"type": "one"}, {"type": "two"}]
        self.assertEqual(normalize_summary(impossible), generic_summary())

        huge = generic_summary("parsed")
        huge["message_count"] = MAX_MESSAGE_COUNT + 1
        self.assertEqual(normalize_summary(huge), generic_summary())

    def test_huge_integer_and_normalized_key_collision_fall_back(self):
        huge_integer = generic_summary("parsed")
        huge_integer["message_count"] = 1
        huge_integer["messages"] = [{"height": 1 << MAX_INTEGER_BITS}]
        self.assertEqual(normalize_summary(huge_integer), generic_summary())

        prefix = "k" * MAX_TOKEN_LENGTH
        collision = generic_summary("parsed")
        collision["message_count"] = 1
        collision["messages"] = [{prefix + "a": "one", prefix + "b": "two"}]
        self.assertEqual(normalize_summary(collision), generic_summary())

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


PRIMARY = {
    "type": "gno.bank.MsgSend",
    "category": "bank",
    "action": "send",
    "label": "Send Tokens",
}


class PublicTransactionSummaryTests(unittest.TestCase):
    def test_sanitizer_builds_a_compact_allowlisted_copy(self):
        stored = {
            "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
            "message_count": 1, "messages_truncated": False, "primary": dict(PRIMARY),
            "messages": [{**PRIMARY, "sender": "g1sender", "memo": "secret"}],
            "internal_error": "secret",
        }
        public = _public_transaction_summary(stored)
        self.assertIsNotNone(public)
        self.assertEqual(public.model_dump(exclude_unset=True)["messages"], [{**PRIMARY, "sender": "g1sender"}])

    def test_sanitizer_rejects_an_oversized_compact_summary(self):
        detail_fields = {
            key: "x" * 160
            for key in (
                "sender", "recipient", "amount", "send", "package_path",
                "package_name", "function", "spend_limit", "spend_period",
            )
        }
        stored = {
            "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
            "message_count": 20, "messages_truncated": False, "primary": dict(PRIMARY),
            "messages": [{**PRIMARY, **detail_fields} for _ in range(20)],
        }
        self.assertIsNone(_public_transaction_summary(stored))


if __name__ == "__main__":
    unittest.main()
