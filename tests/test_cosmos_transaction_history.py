import asyncio
import unittest
from types import SimpleNamespace

from api.cosmos.account_routes import router as cosmos_router
from api.cosmos.cache import RequestCache
from api.cosmos.service import CosmosService
from api.cosmos.transaction_endpoint_policy import _decode_history_cursor


def tx_payload(height: int, *, total: int = 1, marker: str = "A"):
    return {
        "txs": [{
            "body": {
                "messages": [{"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": "atone1sender"}],
                "memo": "history",
            },
            "auth_info": {"fee": {"amount": [{"amount": "1234", "denom": "uatone"}]}},
        }],
        "tx_responses": [{
            "txhash": marker * 64,
            "height": str(height),
            "timestamp": "2026-09-06T00:00:00Z",
            "code": 0,
            "gas_wanted": "200000",
            "gas_used": "12345",
        }],
        "pagination": {"total": str(total)},
    }


def empty_payload():
    return {"txs": [], "tx_responses": [], "pagination": {"total": "0"}}


def service(get_object, *, height=10_000):
    result = object.__new__(CosmosService)
    result.definition = SimpleNamespace(transport=SimpleNamespace(network_id="atomone"))
    result.cache = RequestCache()
    result.adapter = SimpleNamespace(
        _cached_candidates=lambda _kind: asyncio.sleep(
            0, result=(SimpleNamespace(endpoint="https://rest.example"),)),
        _host=lambda _endpoint: "rest.example",
        _clock=lambda: 0.0,
        node_status=lambda: asyncio.sleep(0, result=SimpleNamespace(local_height=height)),
    )
    result.transport = SimpleNamespace(get_object=get_object)
    return result


class TransactionHistoryTests(unittest.TestCase):
    def test_history_route_is_registered_before_app_level_dynamic_tx_routes(self):
        paths = [route.path for route in cosmos_router.routes]
        self.assertIn("/api/networks/{network_id}/transactions/history", paths)

    def test_first_page_uses_two_sided_bounded_window_and_can_walk_older(self):
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            if "tx.height%3E%3D8001%20AND%20tx.height%3C%3D10000" in path:
                return tx_payload(9_999, marker="A")
            if "tx.height%3E%3D6001%20AND%20tx.height%3C%3D8000" in path:
                return tx_payload(7_500, marker="B")
            raise AssertionError(path)

        current = service(get_object)
        first = asyncio.run(current.transaction_history(20, None))
        self.assertEqual((first["window_from"], first["window_to"]), (8_001, 10_000))
        self.assertEqual(first["transactions"][0]["height"], 9_999)
        self.assertEqual(first["older_cursor"], "v1.10000.8000.1")
        self.assertFalse(first["has_newer"])

        older = asyncio.run(current.transaction_history(20, first["older_cursor"]))
        self.assertEqual((older["window_from"], older["window_to"]), (6_001, 8_000))
        self.assertEqual(older["transactions"][0]["height"], 7_500)
        self.assertTrue(older["has_newer"])
        self.assertIsNone(older["newer_cursor"])
        self.assertTrue(all("tx.height%3E0" not in path for path in calls))

    def test_busy_window_pages_before_crossing_to_an_older_height_window(self):
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            return tx_payload(9_900, total=41)

        current = service(get_object)
        first = asyncio.run(current.transaction_history(20, None))
        self.assertEqual(first["older_cursor"], "v1.10000.10000.2")
        second = asyncio.run(current.transaction_history(20, first["older_cursor"]))
        self.assertEqual(second["window_page"], 2)
        self.assertEqual(second["older_cursor"], "v1.10000.10000.3")
        self.assertTrue(second["has_newer"])
        self.assertIsNone(second["newer_cursor"])
        self.assertTrue(any("&page=2&limit=20" in path for path in calls))

    def test_sparse_history_advances_only_a_bounded_number_of_empty_windows(self):
        calls = []

        async def get_object(_endpoint, path, **_kwargs):
            calls.append(path)
            return empty_payload()

        current = service(get_object, height=100_000)
        result = asyncio.run(current.transaction_history(20, None))
        self.assertEqual(len(calls), 8)
        self.assertEqual((result["window_from"], result["window_to"]), (84_001, 86_000))
        self.assertEqual(result["older_cursor"], "v1.100000.84000.1")
        self.assertTrue(result["has_older"])
        self.assertEqual(result["transactions"], [])

    def test_identical_live_viewers_share_one_single_flight_history_request(self):
        calls = 0

        async def get_object(_endpoint, _path, **_kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return tx_payload(9_999)

        current = service(get_object)

        async def run():
            return await asyncio.gather(
                current.transaction_history(20, None),
                current.transaction_history(20, None),
            )

        left, right = asyncio.run(run())
        self.assertEqual(calls, 1)
        self.assertEqual(left, right)

    def test_cursor_is_strict_and_keeps_window_alignment(self):
        self.assertEqual(_decode_history_cursor("v1.10000.8000.3"), (10_000, 8_000, 3))
        for invalid in (
            "10000.8000.3",
            "v1.10000.8001.3",
            "v1.8000.10000.1",
            "v1.10000.8000.0",
            "v1.10000.8000.10001",
        ):
            with self.assertRaises(ValueError):
                _decode_history_cursor(invalid)


if __name__ == "__main__":
    unittest.main()
