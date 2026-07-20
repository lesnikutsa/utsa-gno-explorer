import dataclasses
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from indexer.valopers_parser import (
    MAX_DESCRIPTION_CHARS,
    ValoperListEntry,
    ValoperProfile,
    parse_valoper_detail,
    parse_valopers_list,
)
from scripts import probe_valopers
from tests.test_valopers_source import FakeClient, response

OPERATOR = "g1" + "x" * 38
OTHER = "g1" + "y" * 38
SIGNING = "g1" + "z" * 38
PUBKEY = "gpub1" + "q" * 64


def entry(moniker="UTSA", operator=OPERATOR, profile=None):
    profile = operator if profile is None else profile
    return (
        f" * [{moniker}](/r/gnops/valopers:{operator}) - "
        f"[profile](/r/demo/profile:u/{profile})"
    )


def detail(description="Reliable validator", **values):
    data = {
        "moniker": "UTSA",
        "operator": OPERATOR,
        "signing": SIGNING,
        "pubkey": PUBKEY,
        "server": "data-center",
        "profile": OPERATOR,
    }
    data.update(values)
    return (
        "Valoper's details:\n"
        f"## {data['moniker']}\n{description}\n\n"
        f"- Operator Address: {data['operator']}\n"
        f"- Signing Address: {data['signing']}\n"
        f"- Signing PubKey: {data['pubkey']}\n"
        f"- Server Type: {data['server']}\n\n"
        f"[Profile link](/r/demo/profile:u/{data['profile']})\n"
    )


class ListParserTests(unittest.TestCase):
    def test_one_entry_and_immutable_output(self):
        parsed = parse_valopers_list(entry())
        self.assertEqual(parsed, (ValoperListEntry("UTSA", OPERATOR),))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed[0].moniker = "changed"

    def test_multiple_entries_preserve_order(self):
        parsed = parse_valopers_list(entry("UTSA") + "\n" + entry("Node Two", OTHER))
        self.assertEqual([item.moniker for item in parsed], ["UTSA", "Node Two"])

    def test_instructions_and_pager_are_ignored(self):
        rendered = "# Registration\nFollow these instructions.\n\n" + entry() + "\n\n[Next](/?page=2)"
        self.assertEqual(len(parse_valopers_list(rendered)), 1)

    def test_later_page_and_empty_registry(self):
        self.assertEqual(len(parse_valopers_list(entry() + "\n[Previous](?page=1)")), 1)
        self.assertEqual(parse_valopers_list("No valopers to display."), ())

    def test_invalid_monikers(self):
        for moniker in ("-bad", "bad-", "bad!name", "é", "x" * 33):
            with self.subTest(moniker=moniker), self.assertRaises(ValueError):
                parse_valopers_list(entry(moniker))

    def test_invalid_mismatch_duplicate_and_malformed_entries(self):
        cases = (
            entry(operator="g1short"),
            entry(profile=OTHER),
            entry() + "\n" + entry("Again"),
            " * [UTSA] malformed",
        )
        for rendered in cases:
            with self.subTest(rendered=rendered), self.assertRaises(ValueError):
                parse_valopers_list(rendered)

    def test_requires_string_and_bounds_input(self):
        with self.assertRaises(TypeError):
            parse_valopers_list(None)
        with self.assertRaises(ValueError):
            parse_valopers_list("é" * 600_000)


class DetailParserTests(unittest.TestCase):
    def test_canonical_detail_and_immutable_result(self):
        parsed = parse_valoper_detail(detail())
        self.assertEqual(parsed.moniker, "UTSA")
        self.assertEqual(parsed.operator_address, OPERATOR)
        self.assertEqual(parsed.signing_address, SIGNING)
        self.assertEqual(parsed.signing_pubkey, PUBKEY)
        self.assertEqual(parsed.server_type, "data-center")
        self.assertEqual(parsed.profile_path, f"/r/demo/profile:u/{OPERATOR}")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed.description = "changed"

    def test_multiline_markdown_and_blank_lines_are_preserved(self):
        description = "First line\n\n* markdown\n[link](/example)"
        self.assertEqual(parse_valoper_detail(detail(description)).description, description)

    def test_description_cannot_spoof_fixed_tail(self):
        fake = (
            "Operator notes\n- Operator Address: g1fake\n"
            "- Signing Address: g1fake\n- Signing PubKey: gpub1fake\n"
            "- Server Type: cloud\n[Profile link](/r/demo/profile:u/g1fake)"
        )
        parsed = parse_valoper_detail(detail(fake))
        self.assertEqual(parsed.description, fake)
        self.assertEqual(parsed.operator_address, OPERATOR)
        self.assertEqual(parsed.server_type, "data-center")

    def test_moniker_description_and_prefix_validation(self):
        for rendered in (detail(moniker="bad!"), detail(""), detail("ok").replace("Valoper's", "Other", 1)):
            with self.subTest(rendered=rendered[:40]), self.assertRaises(ValueError):
                parse_valoper_detail(rendered)
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail("x" * (MAX_DESCRIPTION_CHARS + 1)))

    def test_invalid_tail_variants_fail_closed(self):
        canonical = detail()
        cases = [
            canonical.replace(f"- Signing Address: {SIGNING}\n", ""),
            canonical.replace(f"- Signing Address: {SIGNING}\n", f"- Signing Address: {SIGNING}\n- Signing Address: {SIGNING}\n"),
            canonical.replace(f"- Operator Address: {OPERATOR}\n- Signing Address: {SIGNING}", f"- Signing Address: {SIGNING}\n- Operator Address: {OPERATOR}"),
            detail(operator="g1short"), detail(signing="g1short"),
            detail(pubkey="gpub1INVALID"), detail(server="office"), detail(profile=OTHER),
            canonical + "unexpected",
            "invalid address g1short", "unknown address g1short",
        ]
        for rendered in cases:
            with self.subTest(rendered=rendered[-80:]), self.assertRaises(ValueError):
                parse_valoper_detail(rendered)


class ParseCliTests(unittest.TestCase):
    status_payload = {"result": {"node_info": {"network": "test-13"}, "sync_info": {"latest_block_height": "123", "catching_up": False}}}

    def run_main(self, argv, body):
        client = FakeClient(response(body.encode()))
        stdout, stderr = StringIO(), StringIO()
        with patch("scripts.probe_valopers.configured_rpc_urls", return_value=["https://user:secret@example.invalid"]), patch(
            "scripts.probe_valopers.configured_chain_id", return_value="test-13"
        ), patch("scripts.probe_valopers.select_healthy_rpc", return_value=(client, self.status_payload)), redirect_stdout(stdout), redirect_stderr(stderr):
            code = probe_valopers.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), client

    def test_root_page_and_detail_parse_summaries(self):
        secret_description = "x" * 200 + "private full description"
        cases = ((["--parse"], entry(), "parsed_kind=list entries=1"), (["--page-query", "?page=2", "--parse"], entry("Page Node"), "last_moniker='Page Node'"), (["--operator-address", OPERATOR, "--parse"], detail(secret_description), "parsed_kind=detail moniker='UTSA'"))
        for argv, body, expected in cases:
            code, output, errors, client = self.run_main(argv, body)
            self.assertEqual((code, errors), (0, ""))
            self.assertIn(expected, output)
            self.assertNotIn("private full description", output)
            self.assertTrue(all(call[1]["height"] == 123 for call in client.calls))

    def test_parse_failure_is_safe_and_nonzero(self):
        secret = "complete-render-body-secret"
        code, output, errors, _ = self.run_main(["--parse"], secret)
        self.assertEqual(code, 1)
        self.assertIn("render did not match", errors)
        self.assertNotIn(secret, output + errors)
        self.assertNotIn("user:secret", output + errors)


if __name__ == "__main__":
    unittest.main()
