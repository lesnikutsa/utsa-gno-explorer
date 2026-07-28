import unittest
from dataclasses import replace
from unittest.mock import patch

from governance.gno import (GovernanceDiscovery, GovernanceParseError,
    GovernanceProposalSummary, GovernanceSource, discover_governance,
    discover_governance_proposal)
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

    def test_full_discovery_streams_every_list_detail_and_votes_render(self):
        renders = {
            "": "### Prop #1 - One\nStatus: ACTIVE\n[2](?page=2)",
            "?page=2": "### Prop #0 - Zero\nStatus: ACTIVE\n[1](?page=1)",
            "1": detail().replace("#20", "#1").replace("Add validators", "One"),
            "1/votes": "No votes", "0": detail().replace("#20", "#0").replace("Add validators", "Zero"),
            "0/votes": "No votes",
        }
        streamed = {}
        result = discover_governance(
            FakeClient(renders), GovernanceSource("topaz-1", "rpc", 9, "gno.land/r/gov/dao"),
            raw_sink=lambda name, render: streamed.__setitem__(name, render),
        )
        self.assertEqual(set(streamed), {"list/root", "list/?page=2", "proposal/1",
                                         "proposal/1/votes", "proposal/0", "proposal/0/votes"})
        self.assertEqual(result.raw_renders, {})

    def test_targeted_discovery_streams_exact_detail_and_votes(self):
        streamed = {}
        source = GovernanceSource("topaz-1", "rpc", 9, "gno.land/r/gov/dao")
        client = FakeClient({"0": detail().replace("#20", "#0"), "0/votes": "No votes"})
        result = discover_governance_proposal(
            client, source, GovernanceProposalSummary(0, "Add validators", None, None, "ACTIVE"),
            capture_raw=False, raw_sink=lambda name, render: streamed.__setitem__(name, render),
        )
        self.assertEqual(set(streamed), {"proposal/0", "proposal/0/votes"})
        self.assertEqual(result.raw_renders, {})
        self.assertEqual(len(discover_governance_proposal(
            client, source, GovernanceProposalSummary(0, "Add validators", None, None, "ACTIVE"),
            capture_raw=True,
        ).raw_renders), 2)

    def test_single_proposal_is_pinned_and_can_stream_without_capture(self):
        client = FakeClient({"20": detail(), "20/votes": "No votes"})
        streamed = {}
        result = discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20,
                                     raw_sink=lambda name, render: streamed.__setitem__(name, render))
        self.assertEqual([call[2] for call in client.calls], [88, 88])
        self.assertEqual(len(streamed), 2)
        self.assertEqual(result.raw_renders, {})

    def test_capture_raw_and_total_limit(self):
        raw_detail = detail().replace("Add validators", r"Add 6 validator\(s\) to the valset")
        client = FakeClient({"20": raw_detail, "20/votes": "No votes"})
        result = discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20, capture_raw=True)
        self.assertEqual(set(result.raw_renders), {"proposal/20", "proposal/20/votes"})
        self.assertEqual(result.raw_renders["proposal/20"], raw_detail)
        self.assertIn(r"validator\(s\)", result.raw_renders["proposal/20"])
        self.assertEqual(result.proposals[0].title, "Add 6 validator(s) to the valset")
        self.assertEqual(result.to_dict(include_raw=True)["proposals"][0]["title"], "Add 6 validator(s) to the valset")
        with patch("governance.gno.MAX_TOTAL_RAW_BYTES", 10):
            with self.assertRaisesRegex(GovernanceParseError, "total size"):
                discover_governance(client, GovernanceSource("topaz-1", "rpc", 88, "gno.land/r/gov/dao"), proposal_id=20, capture_raw=True)

    def test_escaped_and_unescaped_titles_compare_equal_but_real_difference_warns(self):
        renders = {
            "": r"# GovDAO\n## Proposals\n### Prop #20 - Add 6 validator\(s\)\nStatus: ACCEPTED",
            "20": detail().replace("Add validators", "Add 6 validator(s)"),
            "20/votes": "No votes",
        }
        renders[""] = renders[""].replace(r"\n", "\n")
        result = discover_governance(FakeClient(renders), GovernanceSource("topaz-1", "rpc", 1, "gno.land/r/gov/dao"))
        self.assertFalse(any("title differs" in warning for warning in result.proposals[0].parse_warnings))
        renders["20"] = detail().replace("Add validators", "A genuinely different title")
        result = discover_governance(FakeClient(renders), GovernanceSource("topaz-1", "rpc", 1, "gno.land/r/gov/dao"))
        self.assertTrue(any("title differs" in warning for warning in result.proposals[0].parse_warnings))

    def test_proposal_count_is_independent_from_first_and_latest_ids(self):
        template = discover_governance(
            FakeClient({"20": detail(), "20/votes": "No votes"}),
            GovernanceSource("topaz-1", "rpc", 1, "gno.land/r/gov/dao"),
            proposal_id=20,
        ).proposals[0]
        source = GovernanceSource("topaz-1", "rpc", 1, "gno.land/r/gov/dao")
        topaz_like = GovernanceDiscovery(source, True, 5, tuple(replace(template, proposal_id=value) for value in range(21)))
        self.assertEqual(
            {key: topaz_like.to_dict()[key] for key in ("proposal_count", "first_proposal_id", "latest_proposal_id")},
            {"proposal_count": 21, "first_proposal_id": 0, "latest_proposal_id": 20},
        )
        sparse = GovernanceDiscovery(source, True, 1, (replace(template, proposal_id=10), replace(template, proposal_id=5)))
        self.assertEqual((sparse.to_dict()["proposal_count"], sparse.to_dict()["first_proposal_id"], sparse.to_dict()["latest_proposal_id"]), (2, 5, 10))
        empty = GovernanceDiscovery(source, True, 1, ()).to_dict()
        self.assertEqual((empty["proposal_count"], empty["first_proposal_id"], empty["latest_proposal_id"]), (0, None, None))


if __name__ == "__main__":
    unittest.main()
