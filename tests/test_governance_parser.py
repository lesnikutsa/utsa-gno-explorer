import unittest

from governance.gno import GovernanceParseError, parse_detail, parse_proposal_list, parse_votes, pager_paths


class GovernanceParserTests(unittest.TestCase):
    def test_list_fields_crlf_unknown_and_links(self):
        rendered = "### [Prop #20 - Add validators](gno.land/r/gov/dao:20)\r\n\r\nAuthor: [Alice](gno.land/r/demo/users:g1abc)\r\nTiers eligible to vote: T1, T2, T3\r\nStatus: accepted\r\n"
        proposals, warnings = parse_proposal_list(rendered)
        self.assertEqual((proposals[0].proposal_id, proposals[0].title, proposals[0].status), (20, "Add validators", "ACCEPTED"))
        self.assertEqual(proposals[0].eligible_tiers, ("T1", "T2", "T3"))
        self.assertEqual(warnings, [])

    def test_unknown_status_is_not_active(self):
        proposals, warnings = parse_proposal_list("### Prop #1 - Future\nStatus: PAUSED")
        self.assertEqual(proposals[0].status, "UNKNOWN")
        self.assertTrue(warnings)

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaises(GovernanceParseError):
            parse_proposal_list("### Prop #1 - One\nStatus: ACTIVE\n### Prop #1 - Two\nStatus: REJECTED")

    def test_detail_separates_description_and_metadata(self):
        rendered = "## Prop #2 - Title\nAuthor: g1" + "a" * 38 + "\n\nFirst line\nSecond line\n\nThis proposal contains the following metadata:\nRun executor\nExecutor created in: gno.land/r/demo/executor\n---\nStatus: REJECTED\nActions\nunsafe\nDetailed voting list"
        detail = parse_detail(rendered, 2)
        self.assertEqual(detail["description"], "First line\nSecond line")
        self.assertEqual(detail["executor_text"], "Run executor")
        self.assertNotIn("unsafe", detail["description"])

    def test_votes_recognized_empty_and_unknown(self):
        status, votes, _ = parse_votes("- g1" + "a" * 38 + " | YES | T1 | 10")
        self.assertEqual((status, votes[0].option), ("parsed", "YES"))
        self.assertEqual(parse_votes("No votes")[0], "empty")
        self.assertEqual(parse_votes("new table format")[0], "unparsed")

    def test_only_internal_pager_links(self):
        rendered = "[Next](?page=2) [remote](https://example.com/?page=3) [vote](20/votes)"
        self.assertEqual(pager_paths(rendered, "gno.land/r/gov/dao"), ["?page=2"])


if __name__ == "__main__": unittest.main()
