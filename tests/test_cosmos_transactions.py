import unittest

from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.transactions import normalize_transactions


def payload(message=None, **response):
    message = message or {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": "atone1sender"}
    return {"txs": [{"body": {"messages": [message], "memo": "hello"},
                     "auth_info": {"fee": {"amount": [{"amount": "1234", "denom": "uatone"}]}}}],
            "tx_responses": [{"txhash": "A" * 64, "height": "42", "timestamp": "2026-08-31T00:00:00Z",
                              "code": 0, "gas_wanted": "200000", "gas_used": "12345", **response}],
            "pagination": {"total": "1"}}


class TransactionNormalizationTests(unittest.TestCase):
    def test_success_fields_fee_sender_and_action(self):
        rows, total = normalize_transactions(payload(), 20)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["primary_action"], "Send")
        self.assertEqual((rows[0]["height"], rows[0]["gas_wanted"], rows[0]["gas_used"]), (42, 200000, 12345))
        self.assertEqual((rows[0]["fee_amount"], rows[0]["fee_denom"], rows[0]["sender"]), ("1234", "uatone", "atone1sender"))
        self.assertTrue(rows[0]["success"])

    def test_failed_multiple_and_unknown_fallback(self):
        data = payload({"@type": "/custom.module.v1.MsgDoThing"}, code=7)
        data["txs"][0]["body"]["messages"].append({"@type": "/cosmos.gov.v1beta1.MsgVote"})
        rows, _ = normalize_transactions(data, 20)
        self.assertFalse(rows[0]["success"])
        self.assertEqual((rows[0]["code"], rows[0]["message_count"], rows[0]["primary_action"]), (7, 2, "DoThing"))

    def test_malformed_hash_and_oversized_result_are_rejected(self):
        data = payload(); data["tx_responses"][0]["txhash"] = "bad"
        with self.assertRaises(MalformedUpstreamResponse): normalize_transactions(data, 20)
        data = payload(); data["txs"] *= 2; data["tx_responses"] *= 2
        with self.assertRaises(MalformedUpstreamResponse): normalize_transactions(data, 1)

    def test_empty_result(self):
        self.assertEqual(normalize_transactions({"txs": [], "tx_responses": [], "pagination": {"total": "0"}}, 20), ([], 0))
