import unittest

from governance.gno import (
    GovernanceParseError,
    _unescape_markdown_text,
    pager_paths,
    parse_detail,
    parse_proposal_list,
    parse_votes,
)

ADDRESS = "g1" + "a" * 38
OFFICIAL_LIST = f"""# GovDAO

## Members

[> Go to Memberstore <](/r/gov/dao/v3/memberstore)

## Proposals

### [Prop #20 - Add validators](/r/gov/dao:20)

Author: {ADDRESS}

Status: ACCEPTED

Tiers eligible to vote: T1, T2, T3

---

### [Prop #19 - Open proposal](/r/gov/dao:19)

Author: [@alice](/u/alice)
Status: ACTIVE

---

**1** | [2](?page=2) | ... | [5](?page=5)
"""


def detail(status_line="- **PROPOSAL HAS BEEN ACCEPTED**", percentages=None, reason=""):
    percentages = percentages or ("100", "0", "0")
    return f"""## Prop #20 - Add validators

Author: [@alice](/u/alice)

First description line.
Second description line.

This proposal contains the following metadata:

Executor description

Executor created in: gno.land/r/demo/executor

---

### Stats

{status_line}
{reason}
- Tiers eligible to vote: T1, T2, T3
- YES PERCENT: {percentages[0]}%
- NO PERCENT: {percentages[1]}%
- ABSTAIN PERCENT: {percentages[2]}%

[Detailed voting list](/r/gov/dao:20/votes)

---

### Actions

Do not include this action.
"""


class GovernanceParserTests(unittest.TestCase):
    def test_title_markdown_unescape_is_bounded_to_known_punctuation(self):
        self.assertEqual(
            _unescape_markdown_text(r"Add 6 validator\(s\) to the valset"),
            "Add 6 validator(s) to the valset",
        )
        self.assertEqual(_unescape_markdown_text(r"onbloc\-val\-01"), "onbloc-val-01")
        self.assertEqual(_unescape_markdown_text(r"\[Fix\] \#1 \_now\_ \*safe\*"), "[Fix] #1 _now_ *safe*")
        self.assertEqual(_unescape_markdown_text(r"value\q"), r"value\q")

    def test_official_list_shape_and_picker(self):
        proposals, warnings = parse_proposal_list(OFFICIAL_LIST.replace("\n", "\r\n"))
        self.assertEqual([(p.proposal_id, p.status) for p in proposals], [(20, "ACCEPTED"), (19, "ACTIVE")])
        self.assertEqual(proposals[0].eligible_tiers, ("T1", "T2", "T3"))
        self.assertEqual(proposals[1].author_display, "@alice")
        self.assertEqual(warnings, [])
        self.assertEqual(pager_paths(OFFICIAL_LIST, "gno.land/r/gov/dao"), ["?page=2", "?page=5"])

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaisesRegex(GovernanceParseError, "duplicate"):
            parse_proposal_list("### Prop #1 - One\nStatus: ACTIVE\n### Prop #1 - Two\nStatus: REJECTED")

    def test_accepted_detail_sections_percentages_and_metadata(self):
        parsed = parse_detail(detail(percentages=("99.5", "0.25", "0.25")), 20)
        self.assertEqual(parsed["status"], "ACCEPTED")
        self.assertEqual(parsed["detail_parse_status"], "parsed")
        self.assertEqual(parsed["eligible_tiers"], ("T1", "T2", "T3"))
        self.assertEqual((parsed["yes_percent"], parsed["no_percent"], parsed["abstain_percent"]), (99.5, .25, .25))
        self.assertEqual(parsed["description"], "First description line.\nSecond description line.")
        self.assertEqual(parsed["executor_text"], "Executor description")
        self.assertEqual(parsed["executor_creation_realm"], "gno.land/r/demo/executor")
        self.assertNotIn("Stats", parsed["description"])
        self.assertNotIn("Actions", parsed["description"])

    def test_rejected_active_reason_and_unknown_status(self):
        rejected = parse_detail(detail("- **PROPOSAL HAS BEEN DENIED**", reason="- REASON: Insufficient support"), 20)
        self.assertEqual((rejected["status"], rejected["rejection_reason"]), ("REJECTED", "Insufficient support"))
        self.assertEqual(parse_detail(detail("- Proposal is open for votes"), 20)["status"], "ACTIVE")
        unknown = parse_detail(detail("- Future status"), 20)
        self.assertEqual((unknown["status"], unknown["detail_parse_status"]), ("UNKNOWN", "partial"))
        self.assertTrue(unknown["warnings"])

    def test_invalid_percentage_is_null_with_warning(self):
        parsed = parse_detail(detail(percentages=("nan", "101", "bad")), 20)
        self.assertIsNone(parsed["yes_percent"])
        self.assertIsNone(parsed["no_percent"])
        self.assertIsNone(parsed["abstain_percent"])
        self.assertEqual(len(parsed["warnings"]), 3)

    def test_detail_id_mismatch_is_fatal(self):
        with self.assertRaisesRegex(GovernanceParseError, "does not match"):
            parse_detail(detail(), 21)

    def test_official_grouped_votes(self):
        rendered = f"""# Proposal #20 - Vote List

YES from T1 (VPPM 3):

- {ADDRESS}
- [@alice](/u/alice)

NO from T2 (VPPM 2):
- [{ADDRESS}](/u/address)

ABSTAIN from T3 (VPPM 1):
- [@bob](/u/bob)
"""
        status, votes, warnings = parse_votes(rendered)
        self.assertEqual(status, "parsed")
        self.assertEqual(len(votes), 4)
        self.assertEqual((votes[0].option, votes[0].tier, votes[0].voting_power), ("YES", "T1", "3"))
        self.assertEqual(votes[1].voter_display, "@alice")
        self.assertIsNone(votes[1].voter_address)
        self.assertEqual(votes[2].voter_address, ADDRESS)
        self.assertEqual(votes[3].option, "ABSTAIN")
        self.assertEqual(warnings, [])

    def test_empty_and_unknown_votes(self):
        for text in (
            "# Proposal #20 - Vote List\n\nNo one voted yet.\n",
            "No votes",
            "No vote has been cast",
        ):
            self.assertEqual(parse_votes(text)[0], "empty")
        self.assertEqual(parse_votes("new unexplained format")[0], "unparsed")

    def test_stats_are_scoped_and_description_keeps_user_separator(self):
        rendered = f"""## Prop #20 - Scoped values

Author: {ADDRESS}

First paragraph.
PROPOSAL HAS BEEN DENIED
- YES PERCENT: 100%
- Tiers eligible to vote: T9

---

Second paragraph.

This proposal contains the following metadata:

Executor text with PROPOSAL HAS BEEN DENIED
- REASON: False executor reason
- YES PERCENT: 99%
Executor created in: gno.land/r/demo/real

---

### Stats

- **PROPOSAL HAS BEEN ACCEPTED**
- Tiers eligible to vote: T1, T2, T3
- YES PERCENT: 75%
- NO PERCENT: 25%
- ABSTAIN PERCENT: 0%

[Detailed voting list](/r/gov/dao:20/votes)
"""
        parsed = parse_detail(rendered, 20)
        self.assertEqual(parsed["status"], "ACCEPTED")
        self.assertEqual(parsed["eligible_tiers"], ("T1", "T2", "T3"))
        self.assertEqual((parsed["yes_percent"], parsed["no_percent"], parsed["abstain_percent"]), (75.0, 25.0, 0.0))
        self.assertIsNone(parsed["rejection_reason"])
        self.assertIn("First paragraph.\nPROPOSAL HAS BEEN DENIED", parsed["description"])
        self.assertIn("---\n\nSecond paragraph.", parsed["description"])
        self.assertEqual(parsed["executor_creation_realm"], "gno.land/r/demo/real")

    def test_description_without_metadata_uses_separator_before_stats(self):
        rendered = f"""## Prop #20 - Horizontal rules

Author: {ADDRESS}

First paragraph.

---

Second paragraph.

---

### Stats

- Proposal is open for votes
"""
        parsed = parse_detail(rendered, 20)
        self.assertEqual(parsed["description"], "First paragraph.\n\n---\n\nSecond paragraph.")
        self.assertEqual(parsed["status"], "ACTIVE")

    def test_external_and_action_links_are_not_pagers(self):
        rendered = "[Next](?page=2) [remote](https://example.com/?page=3) [vote](20/votes)"
        self.assertEqual(pager_paths(rendered, "gno.land/r/gov/dao"), ["?page=2"])


if __name__ == "__main__":
    unittest.main()
