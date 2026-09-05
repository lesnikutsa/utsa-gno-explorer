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

    def test_v050_top_level_total_is_supported(self):
        data = payload()
        data["pagination"] = None
        data["total"] = "37"
        _rows, total = normalize_transactions(data, 20)
        self.assertEqual(total, 37)

    def test_matching_modern_and_legacy_totals_are_allowed_but_conflicts_are_rejected(self):
        data = payload()
        data["total"] = "1"
        self.assertEqual(normalize_transactions(data, 20)[1], 1)
        data["total"] = "2"
        with self.assertRaises(MalformedUpstreamResponse):
            normalize_transactions(data, 20)


class TransactionServiceTests(unittest.TestCase):
    @staticmethod
    def service(responses):
        service = object.__new__(CosmosService)
        service.adapter = SimpleNamespace(
            _cached_candidates=lambda _kind: asyncio.sleep(0, result=(SimpleNamespace(endpoint="https://rpc.example"),)),
            _host=lambda _endpoint: "rest.example",
            _clock=lambda: 0.0,
            node_status=lambda: asyncio.sleep(0, result=SimpleNamespace(local_height=10_000)),
            rest_failover=None)
        service.transport = SimpleNamespace(
            get_object=lambda _endpoint, _path, **_kwargs: asyncio.sleep(0, result=responses))
        return service

    @staticmethod
    def multi_service(get_object):
        service = object.__new__(CosmosService)
        candidates = (SimpleNamespace(endpoint="https://fast.example"),
                      SimpleNamespace(endpoint="https://good.example"))
        service.adapter = SimpleNamespace(
            _cached_candidates=lambda _kind: asyncio.sleep(0, result=candidates),
            _host=lambda endpoint: endpoint.removeprefix("https://"),
            _clock=lambda: 0.0,
            node_status=lambda: asyncio.sleep(0, result=SimpleNamespace(local_height=10_000)))
        service.transport = SimpleNamespace(get_object=get_object)
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

    def test_v050_transaction_search_uses_recent_query_page_limit_and_top_level_total(self):
        response = payload()
        response["pagination"] = None
        response["total"] = "41"
        service = self.service(response)
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            return response

        service.transport = SimpleNamespace(get_object=get_object)
        result = asyncio.run(service.transactions(20, 2))
        self.assertEqual(calls, [
            "/cosmos/tx/v1beta1/txs?query=tx.height%3E%3D8001&order_by=ORDER_BY_DESC&page=2&limit=20"
        ])
        self.assertNotIn("tx.height%3E0", calls[0])
        self.assertEqual(result["total"], 41)
        self.assertTrue(result["has_older"])
        self.assertTrue(result["has_newer"])

    def test_pre_v050_query_field_error_falls_back_to_bounded_events_with_page_limit(self):
        response = payload()
        service = self.service(response)
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            if "?query=" in path:
                return {"code": 3, "message": "unknown field query"}
            return response

        service.transport = SimpleNamespace(get_object=get_object)
        result = asyncio.run(service.transactions(10, 3))
        self.assertEqual(calls, [
            "/cosmos/tx/v1beta1/txs?query=tx.height%3E%3D8001&order_by=ORDER_BY_DESC&page=3&limit=10",
            "/cosmos/tx/v1beta1/txs?events=tx.height%3E%3D8001&order_by=ORDER_BY_DESC&page=3&limit=10",
        ])
        self.assertEqual(result["state"], "available")

    def test_recent_window_never_reaches_below_height_one(self):
        response = payload()
        service = self.service(response)
        service.adapter.node_status = lambda: asyncio.sleep(0, result=SimpleNamespace(local_height=77))
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            return response

        service.transport = SimpleNamespace(get_object=get_object)
        asyncio.run(service.transactions(20, 1))
        self.assertIn("query=tx.height%3E%3D1", calls[0])

    def test_transaction_indexing_disabled_is_reported(self):
        service = self.service({"code": 13, "message": "transaction indexing is disabled"})
        result = asyncio.run(service.transactions(20, 1))
        self.assertEqual(result["state"], "indexing_unavailable")
        self.assertEqual(result["transactions"], [])

    def test_transaction_page_100_never_exposes_older_page(self):
        response = payload()
        response["pagination"]["total"] = "999999"
        service = self.service(response)
        result = asyncio.run(service.transactions(20, 100))
        self.assertFalse(result["has_older"])

    def test_response_schema_violation_falls_through_candidate(self):
        response = payload()
        response["txs"][0]["body"]["messages"][0]["from_address"] = "x" * 129
        service = self.service(response)
        with self.assertRaises(AllEndpointsUnavailable):
            asyncio.run(service.transactions(20, 1))

    def test_tx_search_does_not_trust_fast_empty_when_later_endpoint_has_rows(self):
        empty = {"txs": [], "tx_responses": [], "pagination": {"total": "0"}}
        found = payload()

        async def get_object(endpoint, _path, **_kwargs):
            return empty if endpoint == "https://fast.example" else found

        service = self.multi_service(get_object)
        result = asyncio.run(service.transactions(20, 1))
        self.assertEqual(result["source_host"], "good.example")
        self.assertEqual(len(result["transactions"]), 1)
        self.assertIn(("tx_search", "https://fast.example"), service._tx_operation_suspect_until)
        ordered = asyncio.run(service._operation_candidates("rest", "tx_search"))
        self.assertEqual([item.endpoint for item in ordered],
                         ["https://good.example", "https://fast.example"])

    def test_all_valid_empty_tx_search_keeps_empty_as_authoritative_fallback(self):
        empty = {"txs": [], "tx_responses": [], "pagination": {"total": "0"}}

        async def get_object(_endpoint, _path, **_kwargs):
            return empty

        service = self.multi_service(get_object)
        result = asyncio.run(service.transactions(20, 1))
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["transactions"], [])
        self.assertFalse(getattr(service, "_tx_operation_suspect_until", {}))

    def test_false_negative_rpc_lookup_is_deprioritized_after_peer_finds_hash(self):
        tx_hash = "B" * 64

        async def get_object(endpoint, _path, **_kwargs):
            if endpoint == "https://fast.example":
                return {"error": {"message": "tx not found"}}
            return {"result": {"hash": tx_hash, "height": "44", "index": "1"}}

        service = self.multi_service(get_object)
        result = asyncio.run(service.transaction_lookup(tx_hash))
        self.assertEqual((result["height"], result["index"]), (44, 1))
        ordered = asyncio.run(service._operation_candidates("rpc", "tx_lookup"))
        self.assertEqual([item.endpoint for item in ordered],
                         ["https://good.example", "https://fast.example"])
