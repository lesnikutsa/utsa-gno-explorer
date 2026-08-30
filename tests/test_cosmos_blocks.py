from datetime import datetime, timedelta, timezone
import unittest

from api.cosmos.blocks import estimate_height_eta, parse_blockchain
from api.cosmos.errors import MalformedUpstreamResponse


def block(height, timestamp):
    return {"height": height, "_time": timestamp}


class EtaTests(unittest.TestCase):
    def test_outlier_is_trimmed_and_estimate_does_not_drift(self):
        origin = datetime(2026, 8, 30, tzinfo=timezone.utc)
        times = [origin]
        for interval in [5] * 49 + [500] + [5] * 50:
            times.append(times[-1] + timedelta(seconds=interval))
        sample = [block(index + 1, value) for index, value in enumerate(times)]
        first, reason = estimate_height_eta(sample, 111, now=times[-1] + timedelta(seconds=1))
        second, _ = estimate_height_eta(sample, 111, now=times[-1] + timedelta(seconds=2))
        self.assertIsNone(reason)
        self.assertEqual(first["average_interval_seconds"], 5)
        self.assertEqual(first["estimated_at"], second["estimated_at"])

    def test_unavailable_overdue_and_overflow_results(self):
        origin = datetime(2026, 8, 30, tzinfo=timezone.utc)
        short = [block(i + 1, origin + timedelta(seconds=i * 5)) for i in range(20)]
        self.assertEqual(estimate_height_eta(short, 30, now=origin)[1], "insufficient_sample")
        full = [block(i + 1, origin + timedelta(seconds=i * 5)) for i in range(101)]
        self.assertEqual(estimate_height_eta(full, 102, now=full[-1]["_time"] + timedelta(seconds=301))[1],
                         "network_appears_stalled")
        overdue, _ = estimate_height_eta(full, 102, now=full[-1]["_time"] + timedelta(seconds=10))
        self.assertEqual(overdue["status"], "overdue_awaiting")
        huge = [block(i + 1, datetime.max.replace(tzinfo=timezone.utc) - timedelta(seconds=(100-i)*5))
                for i in range(101)]
        self.assertEqual(estimate_height_eta(huge, 9_223_372_036_854_775_807,
                         now=huge[-1]["_time"])[1], "date_out_of_range")


class MetadataTests(unittest.TestCase):
    def test_normalizes_metadata(self):
        payload = {"result": {"block_metas": [
            {"block_id": {"hash": "AA"}, "header": {"chain_id": "chain-1", "height": "2",
             "time": "2026-08-30T00:00:05Z", "proposer_address": "BB"}, "num_txs": "3"},
            {"block_id": {"hash": "CC"}, "header": {"chain_id": "chain-1", "height": "1",
             "time": "2026-08-30T00:00:00Z", "proposer_address": "DD"}, "num_txs": "0"}]}}
        self.assertEqual([item["height"] for item in parse_blockchain(
            payload, chain_id="chain-1", minimum=1, maximum=2)], [2, 1])

    def test_rejects_wrong_chain(self):
        item = {"block_id": {"hash": "AA"}, "header": {"chain_id": "wrong", "height": "1",
                "time": "2026-08-30T00:00:00Z", "proposer_address": "BB"}, "num_txs": "0"}
        with self.assertRaises(MalformedUpstreamResponse):
            parse_blockchain({"result": {"block_metas": [item]}}, chain_id="chain-1", minimum=1, maximum=1)

    def test_rejects_missing_negative_typed_and_oversized_transaction_counts(self):
        for value in (None, -1, "-1", True, 2_147_483_648, "2147483648", 1.5):
            with self.subTest(value=value):
                item = {"block_id": {"hash": "AA"}, "header": {"chain_id": "chain-1", "height": "1",
                        "time": "2026-08-30T00:00:00Z", "proposer_address": "BB"}}
                if value is not None:
                    item["num_txs"] = value
                with self.assertRaises(MalformedUpstreamResponse):
                    parse_blockchain({"result": {"block_metas": [item]}},
                                     chain_id="chain-1", minimum=1, maximum=1)
