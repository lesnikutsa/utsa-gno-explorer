import unittest
from unittest.mock import patch

from governance.gno import GovernanceParseError, GovernanceSource, discover_governance
from tests.test_governance_parser import ADDRESS, detail


class FakeClient:
    def __init__(self, renders):
        self.renders = renders
        self.calls = []

    def abci_query(self, path, data, height=None):
        self.calls.append((path, data, height))
        return self.renders[data.split(":", 1)[1]]


class DiscoveryTests(unittest.TestCase):
    def test_pages_pinned_height_raw_default_and_correct_status_counts(self):
        renders = {
            "": f"# GovDAO\n## Proposals\n### [Prop #20 - Add validators](/r/gov/dao:20)\nAuthor: {ADDRESS}\nStatus: ACTIVE\nTiers eligible to vote: T1\n---\n[2](?page=2)",
            "?page=2": "# GovDAO\n## Proposals\n### Prop #19 - Other\nStatus: ACTIVE\n---\n[**1**](?page=1)",
            "20": detail(), "20/votes": "No one voted yet.",
            "19": detail("- Proposal is open for votes").replace("#20", "#19").replace("Add validators", "Other"),
            "19/votes": "No one voted yet.",
        }
        client = FakeClient(renders)
        result = discover_governance(client, GovernanceSource("topaz-1", "rpc", 77, "gno.land/r/gov/dao"))
        self.assertEqual([proposal.proposal_id for proposal in result.proposals], [20, 19])
        self.assertTrue(all(call[2] == 77 for call in client.calls))
        self.assertEqual(result.raw_renders, {})
        self.assertEqual(result.to_dict()["status_counts"], {"active": 1, "accepted": 1, "rejected": 0, "unknown": 0})
        self.assertTrue(any(warning.startswith("Proposal status differs") for warning in result.proposals[0].parse_warnings))
        self.assertTrue(any(warning.startswith("Eligible tiers differ") for warning in result.proposals[0].parse_warnings))

    def test_single_proposal_is_pinned_and_can_stream_without_capture(self):
        client = FakeClient({"20": detail(), "20/votes": "No votes"})
        streamed = {}
        result = discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20,
                                     raw_sink=lambda name, render: streamed.__setitem__(name, render))
        self.assertEqual([call[2] for call in client.calls], [88, 88])
        self.assertEqual(len(streamed), 2)
        self.assertEqual(result.raw_renders, {})

    def test_capture_raw_and_total_limit(self):
        client = FakeClient({"20": detail(), "20/votes": "No votes"})
        result = discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20, capture_raw=True)
        self.assertEqual(set(result.raw_renders), {"proposal/20", "proposal/20/votes"})
        with patch("governance.gno.MAX_TOTAL_RAW_BYTES", 10):
            with self.assertRaisesRegex(GovernanceParseError, "total size"):
                discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20, capture_raw=True)


if __name__ == "__main__":
    unittest.main()
