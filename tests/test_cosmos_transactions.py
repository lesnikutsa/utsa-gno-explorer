import unittest
import asyncio
from types import SimpleNamespace

from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.transactions import normalize_transactions
from api.cosmos.errors import AllEndpointsUnavailable, TransactionNotFound
from api.cosmos.service import CosmosService


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


class TransactionServiceTests(unittest.TestCase):
    @staticmethod
    def service(responses):
        service = object.__new__(CosmosService)
        service.adapter = SimpleNamespace(
            _cached_candidates=lambda _kind: asyncio.sleep(0, result=(SimpleNamespace(endpoint="https://rpc.example"),)),
            _host=lambda _endpoint: "rest.example",
            rest_failover=None)
        service.transport = SimpleNamespace(
            get_object=lambda _endpoint, _path, **_kwargs: asyncio.sleep(0, result=responses))
        return service

    def test_exact_hash_lookup_normalizes_case_and_location(self):
        tx_hash = "ab" * 32
        service = self.service({"result": {"hash": tx_hash, "height": "42", "index": "3"}})
        result = asyncio.run(service.transaction_lookup(tx_hash))
        self.assertEqual(result, {"height": 42, "index": 3, "tx_hash": tx_hash.upper()})

    def test_exact_hash_lookup_distinguishes_not_found_and_index_unavailable(self):
        missing = self.service({"error": {"message": "tx not found"}})
        with self.assertRaises(TransactionNotFound):
            asyncio.run(missing.transaction_lookup("A" * 64))
        unavailable = self.service({"error": {"message": "transaction indexing is disabled"}})
        with self.assertRaises(AllEndpointsUnavailable):
            asyncio.run(unavailable.transaction_lookup("A" * 64))
        with self.assertRaises(ValueError):
            asyncio.run(unavailable.transaction_lookup("not-a-hash"))

    def test_transaction_page_100_never_exposes_older_page(self):
        response = payload()
        response["pagination"]["total"] = "999999"
        service = self.service(response)

        async def failover(_path):
            yield "https://rest.example", response

        service.adapter.rest_failover = failover
        result = asyncio.run(service.transactions(20, 100))
        self.assertFalse(result["has_older"])

    def test_response_schema_violation_falls_through_candidate(self):
        response = payload()
        response["txs"][0]["body"]["messages"][0]["from_address"] = "x" * 129
        service = self.service(response)

        async def failover(_path):
            yield "https://rest.example", response

        service.adapter.rest_failover = failover
        with self.assertRaises(AllEndpointsUnavailable):
            asyncio.run(service.transactions(20, 1))
