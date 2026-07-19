import base64
import unittest
from pathlib import Path

from indexer.validator_profiles import (
    ED25519_PREFIX, MAX_RESPONSE_BYTES, ProfileSourceError, SourceResponse,
    collect_profiles, match_profiles, normalize_gpub, parse_detail, parse_list_page,
)

FIX = Path(__file__).parent / "fixtures" / "valopers"

class ProfilesTest(unittest.TestCase):
    def read(self, name): return (FIX / name).read_text()

    def test_list_and_pagination(self):
        operators, next_path = parse_list_page(self.read("list_first_page.txt"))
        self.assertEqual(operators, ["g1alpha"])
        self.assertEqual(next_path, "/r/gnops/valopers?page=2")

    def test_duplicate_links_are_deduplicated(self):
        text = "[A](/r/gnops/valopers:g1a)\n[A](/r/gnops/valopers:g1a)"
        self.assertEqual(parse_list_page(text)[0], ["g1a"])

    def test_detail_fields_and_optional_values(self):
        profile = parse_detail(self.read("detail_ed25519.txt"), "g1alpha", 42)
        self.assertEqual(profile.moniker, "Alpha_Node")
        self.assertTrue(profile.keep_running)
        self.assertEqual(profile.source_height, 42)
        beta = parse_detail(self.read("detail_secp256k1.txt"), "g1beta", 42)
        self.assertEqual(beta.description, "")
        self.assertIsNone(beta.keep_running)

    def test_required_fields_rejected(self):
        for field in ("Moniker", "Consensus Public Key"):
            text = self.read("detail_ed25519.txt")
            text = "\n".join(line for line in text.splitlines() if field not in line)
            with self.assertRaises(ProfileSourceError): parse_detail(text, "g1alpha", 1)
        with self.assertRaises(ProfileSourceError): parse_detail(self.read("detail_ed25519.txt"), "", 1)

    def test_oversize_rejected(self):
        with self.assertRaises(ProfileSourceError): parse_list_page("x" * (MAX_RESPONSE_BYTES + 1))

    def test_gpub_key_types_and_values(self):
        ed = parse_detail(self.read("detail_ed25519.txt"), "g1alpha", 1).consensus_pubkey
        sec = parse_detail(self.read("detail_secp256k1.txt"), "g1beta", 1).consensus_pubkey
        self.assertEqual(normalize_gpub(ed), ("/tm.PubKeyEd25519", base64.b64encode(bytes(range(32))).decode()))
        self.assertEqual(normalize_gpub(sec), ("/tm.PubKeySecp256k1", base64.b64encode(bytes(range(33))).decode()))

    def test_invalid_gpub_fails_closed(self):
        good = parse_detail(self.read("detail_ed25519.txt"), "g1alpha", 1).consensus_pubkey
        values = [good[:-1] + ("q" if good[-1] != "q" else "p"), "xpub" + good[4:], good[:-8], good[:8].upper()+good[8:], good[:10]+"!"+good[11:]]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_gpub(value)

    def test_matching_exact_unmatched_invalid_and_ambiguous(self):
        alpha = parse_detail(self.read("detail_ed25519.txt"), "g1alpha", 1)
        beta = parse_detail(self.read("detail_secp256k1.txt"), "g1beta", 1)
        key_type, key_value = normalize_gpub(alpha.consensus_pubkey)
        invalid = alpha.__class__(**{**alpha.__dict__, "operator_address":"g1invalid", "consensus_pubkey":"bad"})
        duplicate = alpha.__class__(**{**alpha.__dict__, "operator_address":"g1duplicate"})
        matched = match_profiles([beta, alpha, invalid], [("SIGN", key_type, key_value)])
        self.assertEqual([p.operator_address for p in matched], ["g1alpha", "g1beta", "g1invalid"])
        self.assertEqual([p.match_status for p in matched], ["matched", "unmatched", "invalid_pubkey"])
        ambiguous = match_profiles([alpha, duplicate], [("SIGN", key_type, key_value)])
        self.assertEqual({p.match_status for p in ambiguous}, {"ambiguous"})
        self.assertTrue(all(p.signing_address is None for p in ambiguous))

    def test_height_mismatch_and_loop_abort_collection(self):
        pages = {"gno.land/r/gnops/valopers": self.read("list_first_page.txt"),
                 "gno.land/r/gnops/valopers?page=2": "[A](/r/gnops/valopers:g1alpha)\n[Next](/r/gnops/valopers?page=2)"}
        def query(client, path, height): return SourceResponse(pages[path], height)
        with self.assertRaises(ProfileSourceError): collect_profiles(None, 5, query=query)

    def test_schema_foundation(self):
        schema = (Path(__file__).parents[1] / "database/schema.sql").read_text()
        for text in ("CREATE TABLE validator_profiles", "validator_profiles_signing_address_idx", "validator_profiles_consensus_pubkey_idx", "validator_profiles_moniker_lower_idx", "invalid_pubkey", "ON DELETE SET NULL"):
            self.assertIn(text, schema)

if __name__ == "__main__": unittest.main()
