import json
import unittest
from pathlib import Path

from scripts.inspect_rpc import build_summary, parse_block, parse_status, parse_validators

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class InspectRpcParsingTests(unittest.TestCase):
    def test_parse_status_extracts_chain_height_version_and_sync(self):
        parsed = parse_status(load("status.json"))
        self.assertEqual(parsed, {
            "chain_id": "test13",
            "latest_height": 123,
            "node_version": "0.1.0",
            "catching_up": False,
        })

    def test_parse_block_extracts_header_commit_and_tx_summary(self):
        parsed = parse_block(load("block.json"))
        self.assertEqual(parsed["hash"], "ABC123")
        self.assertEqual(parsed["height"], 123)
        self.assertEqual(parsed["proposer_address"], "VAL1")
        self.assertEqual(parsed["tx_count"], 2)
        self.assertEqual(parsed["transactions"][0]["raw_preview"], "tx-one")
        self.assertEqual(len(parsed["commit_signatures"]), 2)

    def test_parse_validators_extracts_addresses_and_power(self):
        validators = parse_validators(load("validators.json"))
        self.assertEqual(validators[0]["address"], "VAL1")
        self.assertEqual(validators[1]["voting_power"], 20)

    def test_build_summary_identifies_signed_and_missed_validators(self):
        summary = build_summary(load("status.json"), load("block.json"), load("validators.json"))
        self.assertEqual(summary.chain_id, "test13")
        self.assertEqual([v["address"] for v in summary.signed_validators], ["VAL1"])
        self.assertEqual([v["address"] for v in summary.missed_validators], ["VAL2"])


if __name__ == "__main__":
    unittest.main()
