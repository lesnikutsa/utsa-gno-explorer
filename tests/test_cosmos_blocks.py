from datetime import timezone
import asyncio
import unittest

from api.cosmos.blocks import estimate_eta, parse_blockchain
from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.rfc3339 import normalize_rfc3339, parse_rfc3339
from api.cosmos.transport import JsonTransport


class _Response:
    status_code = 200
    def __init__(self, delay=0): self.delay = delay; self.closed = False
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): self.closed = True
    async def aiter_bytes(self):
        await asyncio.sleep(self.delay)
        yield b"{}"


class _Client:
    def __init__(self, response): self.response = response
    def stream(self, *_args, **_kwargs): return self.response


class TransportDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_covers_stream_and_closes_response(self):
        response = _Response(delay=.05)
        transport = JsonTransport(timeout=.01, max_response_bytes=1024, client=_Client(response))
        with self.assertRaisesRegex(Exception, "transport_error"):
            await transport.get_object("https://safe.example", "/status")
        self.assertTrue(response.closed)

    async def test_external_cancellation_is_preserved_and_closes_response(self):
        response = _Response(delay=1)
        transport = JsonTransport(timeout=5, max_response_bytes=1024, client=_Client(response))
        task = asyncio.create_task(transport.get_object("https://safe.example", "/status"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(response.closed)


class Rfc3339Tests(unittest.TestCase):
    def test_nanoseconds_and_offsets_are_normalized_on_python_310(self):
        self.assertEqual(normalize_rfc3339("2026-08-30T12:34:56.123456789Z"),
                         "2026-08-30T12:34:56.123456Z")
        self.assertEqual(normalize_rfc3339("2026-08-30T14:34:56.1+02:00"),
                         "2026-08-30T12:34:56.100000Z")
        self.assertEqual(parse_rfc3339("2026-08-30T12:34:56-03:30").tzinfo, timezone.utc)

    def test_invalid_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_rfc3339("2026-08-30T12:34:56+00:60")


class BlockMetadataTests(unittest.TestCase):
    def metadata(self, height, timestamp):
        return {"block_id": {"hash": "AA"}, "header": {"chain_id": "atomone-1",
            "height": str(height), "time": timestamp, "proposer_address": "BB"}, "num_txs": "0"}

    def test_metadata_uses_shared_timestamp_parser(self):
        payload = {"result": {"block_metas": [self.metadata(42, "2026-08-30T12:34:56.123456789Z")]}}
        blocks = parse_blockchain(payload, network_id="atomone-mainnet", expected_chain_id="atomone-1")
        self.assertEqual(blocks[0]["timestamp"], "2026-08-30T12:34:56.123456Z")

    def test_metadata_rejects_wrong_chain(self):
        payload = {"result": {"block_metas": [self.metadata(42, "2026-08-30T12:34:56Z")]}}
        payload["result"]["block_metas"][0]["header"]["chain_id"] = "wrong"
        with self.assertRaises(Exception):
            parse_blockchain(payload, network_id="atomone-mainnet", expected_chain_id="atomone-1")

    def test_eta_trims_outliers_and_anchors_to_last_block(self):
        blocks = []
        base = parse_rfc3339("2026-08-30T00:00:00Z")
        elapsed = 0
        for height in range(1, 102):
            blocks.append({"height": height, "timestamp": (base.replace(tzinfo=timezone.utc)
                .timestamp() + elapsed)})
            elapsed += 1000 if height in {10, 90} else 5
        for block in blocks:
            from datetime import datetime
            block["timestamp"] = datetime.fromtimestamp(block["timestamp"], timezone.utc).isoformat().replace("+00:00", "Z")
        eta = estimate_eta(blocks, 111)
        self.assertIsNotNone(eta)
        self.assertEqual(eta["remaining_blocks"], 10)
        self.assertAlmostEqual(eta["average_block_seconds"], 5)

    def test_eta_requires_twenty_trimmed_intervals(self):
        blocks = [{"height": height, "timestamp": f"2026-08-30T00:00:{height:02d}Z"} for height in range(1, 20)]
        self.assertIsNone(estimate_eta(blocks, 30))
