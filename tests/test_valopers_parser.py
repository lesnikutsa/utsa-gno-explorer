import dataclasses
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from indexer.valopers_parser import (
    MAX_DESCRIPTION_BYTES,
    MAX_RENDER_BYTES,
    MAX_SIGNING_PUBKEY_LENGTH,
    MIN_SIGNING_PUBKEY_LENGTH,
    ValoperListEntry,
    parse_valoper_detail,
    parse_valopers_list,
)
from scripts import probe_valopers
from indexer.valopers_source import decode_qrender_response
from tests.test_valopers_source import FakeClient, response

OPERATOR = "g1" + "x" * 38
OTHER_OPERATOR = "g1" + "y" * 38
SIGNING = "g1" + "z" * 38
FAKE_SIGNING = "g1" + "w" * 38
# Representative of the long, lowercase Bech32-style form emitted by the realm.
OFFICIAL_STYLE_PUBKEY = (
    "gpub1pgfj7ard9eg82t2t4cnj7m6s52e3qflzuw6kge9t6g7v4h3j2k9m8n7p6q5r4"
    "s3t2u9v8w7x6y5z4acdefghjklmnpq"
)
FAKE_PUBKEY = (
    "gpub1qwertyujppasdfghjklzxcvcnm234567890qwertyujppasdfghjklzxcvcnm"
    "234567890qwertyujppasdfghjkl"
)


def entry(moniker="UTSA", operator=OPERATOR, profile=None):
    profile = operator if profile is None else profile
    return (
        f" * [{moniker}](/r/gnops/valopers:{operator}) - "
        f"[profile](/r/demo/profile:u/{profile})"
    )


def detail(description="Reliable validator", **overrides):
    values = {
        "moniker": "UTSA",
        "operator": OPERATOR,
        "signing": SIGNING,
        "pubkey": OFFICIAL_STYLE_PUBKEY,
        "server": "data-center",
        "profile": OPERATOR,
    }
    values.update(overrides)
    return (
        "Valoper's details:\n"
        f"## {values['moniker']}\n{description}\n\n"
        f"- Operator Address: {values['operator']}\n"
        f"- Signing Address: {values['signing']}\n"
        f"- Signing PubKey: {values['pubkey']}\n"
        f"- Server Type: {values['server']}\n\n"
        f"[Profile link](/r/demo/profile:u/{values['profile']})\n"
    )


class ListParserTests(unittest.TestCase):
    def test_canonical_entry(self):
        self.assertEqual(
            parse_valopers_list(entry()),
            (ValoperListEntry(moniker="UTSA", operator_address=OPERATOR),),
        )

    def test_order_is_preserved(self):
        parsed = parse_valopers_list(entry("UTSA") + "\n" + entry("Node Two", OTHER_OPERATOR))
        self.assertEqual([item.moniker for item in parsed], ["UTSA", "Node Two"])

    def test_realistic_root_instructions_are_ignored(self):
        rendered = (
            "# Valopers registry\nRegister a profile before applying.\n"
            "* [Registration guide](/r/gnops/valopers-help)\n\n" + entry()
        )
        self.assertEqual(len(parse_valopers_list(rendered)), 1)

    def test_realistic_later_page_and_canonical_pager_are_ignored(self):
        rendered = entry() + "\n\n[1](?page=1) | **2** | [3](?page=3)"
        self.assertEqual(len(parse_valopers_list(rendered)), 1)

    def test_absolute_valopers_pager_path_is_not_exempted(self):
        rendered = entry() + "\n[3](/r/gnops/valopers:?page=3)"
        with self.assertRaises(ValueError):
            parse_valopers_list(rendered)

    def test_canonical_empty_registry_must_be_final_meaningful_line(self):
        rendered = "# Registration\nInstructions\n\nNo valopers to display.\n\n"
        self.assertEqual(parse_valopers_list(rendered), ())

    def test_empty_registry_phrase_in_middle_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valopers_list("No valopers to display.\nUnexpected footer")

    def assert_malformed_mixed_with_valid(self, malformed):
        with self.assertRaises(ValueError):
            parse_valopers_list(entry() + "\n" + malformed)

    def test_candidate_without_leading_space_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR)[1:])

    def test_candidate_with_extra_indentation_is_rejected(self):
        self.assert_malformed_mixed_with_valid("  " + entry("Other", OTHER_OPERATOR))

    def test_wrong_profile_label_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR).replace("[profile]", "[account]"))

    def test_wrong_detail_path_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR).replace("/r/gnops/valopers:", "/r/gnops/operators:"))

    def test_wrong_profile_path_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR).replace("/r/demo/profile:u/", "/r/demo/account:u/"))

    def test_trailing_content_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR) + " trailing")

    def test_missing_markdown_closure_is_rejected(self):
        self.assert_malformed_mixed_with_valid(entry("Other", OTHER_OPERATOR)[:-1])

    def test_mismatched_addresses_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_valopers_list(entry(profile=OTHER_OPERATOR))

    def test_duplicate_operator_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valopers_list(entry() + "\n" + entry("Again"))

    def test_ascii_moniker_boundaries_are_enforced(self):
        for moniker in ("-bad", "bad-", "bad!name", "é", "x" * 33):
            with self.subTest(moniker=moniker), self.assertRaises(ValueError):
                parse_valopers_list(entry(moniker))

    def test_input_byte_limit_is_enforced(self):
        with self.assertRaises(ValueError):
            parse_valopers_list("é" * (MAX_RENDER_BYTES // 2 + 1))

    def test_non_string_input_is_rejected(self):
        with self.assertRaises(TypeError):
            parse_valopers_list(None)

    def test_tuple_and_entry_are_immutable(self):
        parsed = parse_valopers_list(entry())
        self.assertIsInstance(parsed, tuple)
        with self.assertRaises(TypeError):
            parsed[0] = parsed[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed[0].moniker = "changed"


class DetailParserTests(unittest.TestCase):
    def test_canonical_document(self):
        parsed = parse_valoper_detail(detail())
        self.assertEqual(parsed.moniker, "UTSA")
        self.assertEqual(parsed.operator_address, OPERATOR)
        self.assertEqual(parsed.signing_address, SIGNING)
        self.assertEqual(parsed.signing_pubkey, OFFICIAL_STYLE_PUBKEY)
        self.assertEqual(parsed.profile_path, f"/r/demo/profile:u/{OPERATOR}")

    def test_all_server_types_are_accepted(self):
        for server_type in ("cloud", "on-prem", "data-center"):
            with self.subTest(server_type=server_type):
                self.assertEqual(parse_valoper_detail(detail(server=server_type)).server_type, server_type)

    def test_multiline_markdown_description_is_preserved(self):
        description = "First line\n* bullet\n[link](/example)"
        self.assertEqual(parse_valoper_detail(detail(description)).description, description)

    def test_blank_lines_and_meaningful_trailing_newline_are_preserved(self):
        description = "First line\n\nLast line\n"
        self.assertEqual(parse_valoper_detail(detail(description)).description, description)

    def test_valid_fake_identity_block_cannot_spoof_final_tail(self):
        fake_block = (
            "Operator notes\n\n"
            f"- Operator Address: {OTHER_OPERATOR}\n"
            f"- Signing Address: {FAKE_SIGNING}\n"
            f"- Signing PubKey: {FAKE_PUBKEY}\n"
            "- Server Type: cloud\n\n"
            f"[Profile link](/r/demo/profile:u/{OTHER_OPERATOR})"
        )
        parsed = parse_valoper_detail(detail(fake_block))
        self.assertEqual(parsed.description, fake_block)
        self.assertEqual(parsed.operator_address, OPERATOR)
        self.assertEqual(parsed.signing_address, SIGNING)
        self.assertEqual(parsed.signing_pubkey, OFFICIAL_STYLE_PUBKEY)
        self.assertEqual(parsed.server_type, "data-center")
        self.assertEqual(parsed.profile_path, f"/r/demo/profile:u/{OPERATOR}")

    def test_exact_2048_byte_description_is_accepted(self):
        description = "x" * MAX_DESCRIPTION_BYTES
        self.assertEqual(parse_valoper_detail(detail(description)).description, description)

    def test_2049_byte_description_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail("x" * (MAX_DESCRIPTION_BYTES + 1)))

    def test_multibyte_utf8_description_boundary(self):
        accepted = "é" * (MAX_DESCRIPTION_BYTES // 2)
        rejected = accepted + "a"
        self.assertEqual(parse_valoper_detail(detail(accepted)).description, accepted)
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(rejected))

    def test_empty_description_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(""))

    def test_non_string_input_is_rejected(self):
        with self.assertRaises(TypeError):
            parse_valoper_detail(None)

    def test_missing_prefix_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail().replace("Valoper's details:", "Details:", 1))

    def test_missing_field_is_rejected(self):
        rendered = detail().replace(f"- Signing Address: {SIGNING}\n", "")
        with self.assertRaises(ValueError):
            parse_valoper_detail(rendered)

    def test_duplicated_field_is_rejected(self):
        field = f"- Signing Address: {SIGNING}\n"
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail().replace(field, field + field))

    def test_reordered_fields_are_rejected(self):
        original = f"- Operator Address: {OPERATOR}\n- Signing Address: {SIGNING}"
        reordered = f"- Signing Address: {SIGNING}\n- Operator Address: {OPERATOR}"
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail().replace(original, reordered))

    def test_invalid_operator_address_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(operator="g1short"))

    def test_invalid_signing_address_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(signing="g1short"))

    def test_short_gpub_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(pubkey="gpub1" + "q" * (MIN_SIGNING_PUBKEY_LENGTH - 6)))

    def test_long_gpub_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(pubkey="gpub1" + "q" * MAX_SIGNING_PUBKEY_LENGTH))

    def test_uppercase_gpub_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(pubkey=OFFICIAL_STYLE_PUBKEY.upper()))

    def test_forbidden_character_gpub_is_rejected(self):
        for forbidden in ("b", "i", "o", "1", " "):
            pubkey = OFFICIAL_STYLE_PUBKEY[:20] + forbidden + OFFICIAL_STYLE_PUBKEY[21:]
            with self.subTest(forbidden=forbidden), self.assertRaises(ValueError):
                parse_valoper_detail(detail(pubkey=pubkey))

    def test_invalid_server_type_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(server="office"))

    def test_mismatched_profile_link_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(profile=OTHER_OPERATOR))

    def test_invalid_address_realm_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail("invalid address g1short")

    def test_unknown_address_realm_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail("unknown address g1short")

    def test_trailing_unexpected_content_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail() + "unexpected")

    def test_moniker_contract_is_enforced(self):
        with self.assertRaises(ValueError):
            parse_valoper_detail(detail(moniker="bad!"))

    def test_profile_is_immutable(self):
        parsed = parse_valoper_detail(detail())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed.description = "changed"


class ParseCliTests(unittest.TestCase):
    status_payload = {
        "result": {
            "node_info": {"network": "test-13"},
            "sync_info": {"latest_block_height": "123", "catching_up": False},
        }
    }

    def run_main(self, argv, body):
        client = FakeClient(response(body.encode()))
        stdout, stderr = StringIO(), StringIO()
        with patch(
            "scripts.probe_valopers.configured_rpc_urls",
            return_value=["https://user:secret@example.invalid/rpc?token=private"],
        ), patch(
            "scripts.probe_valopers.configured_chain_id", return_value="test-13"
        ), patch(
            "scripts.probe_valopers.select_healthy_rpc",
            return_value=(client, self.status_payload),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            code = probe_valopers.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), client

    def test_parse_retains_transport_preview_before_parser_summary(self):
        rendered = "# " + "instructions " * 20 + "\n" + entry()
        code, output, errors, _ = self.run_main(["--parse"], rendered)
        self.assertEqual((code, errors), (0, ""))
        lines = output.splitlines()
        self.assertIn(" preview=", lines[0])
        self.assertTrue(lines[1].startswith("parsed_kind=list "))
        self.assertNotIn(rendered, output)

    def test_without_parse_preserves_exact_transport_summary(self):
        rendered = entry()
        expected_result = decode_qrender_response(response(rendered.encode()), "root", 123)
        code, output, errors, _ = self.run_main([], rendered)
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(output, probe_valopers.format_result(expected_result) + "\n")

    def test_root_parse_summary(self):
        code, output, errors, _ = self.run_main(["--parse"], entry())
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("parsed_kind=list entries=1", output)

    def test_page_parse_summary(self):
        code, output, errors, client = self.run_main(
            ["--page-query", "?page=2", "--parse"], entry("Page Node")
        )
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("last_moniker='Page Node'", output)
        self.assertEqual(len(client.calls), 1)

    def test_detail_parse_summary_is_bounded(self):
        secret_description = "x" * 200 + "private full description"
        code, output, errors, client = self.run_main(
            ["--operator-address", OPERATOR, "--parse"], detail(secret_description)
        )
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("parsed_kind=detail moniker='UTSA'", output)
        self.assertNotIn("private full description", output)
        self.assertNotIn(OFFICIAL_STYLE_PUBKEY, output)
        self.assertTrue(all(call[1]["height"] == 123 for call in client.calls))

    def test_parse_failure_is_safe_and_nonzero(self):
        secret = "complete-render-body-secret"
        code, output, errors, _ = self.run_main(["--parse"], secret)
        self.assertEqual(code, 1)
        self.assertIn("render did not match", errors)
        self.assertNotIn(secret, output + errors)
        self.assertNotIn("user:secret", output + errors)
        self.assertNotIn("token=private", output + errors)


if __name__ == "__main__":
    unittest.main()
