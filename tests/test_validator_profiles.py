import base64
import contextlib
import io
import json
import copy
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from indexer.database import DatabaseError, PostgresDatabase
from indexer.validator_profiles import (
    MAX_PAGES, MAX_PROFILES, MAX_RESPONSE_BYTES, ProfileSourceError,
    SourceResponse, collect_profiles, decode_vm_response, match_profiles,
    normalize_gpub, parse_detail, parse_list_page, query_render,
)
from scripts import sync_validator_profiles
from scripts import init_database

FIX = Path(__file__).parent / "fixtures" / "valopers"
ED_GPUB = "gpub1pggj7ard9eg82cjtv4u52epjx56nzwgjyg9zqqgzqvzq2ps8pqys5zcvp58q7yq3zgf3g9gkzuvpjxsmrsw3u8eqh8zc2g"
SEC_GPUB = "gpub1pgfj7ard9eg82cjtv4u4xetrwqer2dntxyfzxz3pqypqxpq9qcrsszg2pvxq6rs0zqg3yyc5z5tpwxqergd3c8g7ruszzaywaz7"


def response(text, height=42):
    return {"result": {"response": {"height": str(height), "value": base64.b64encode(text.encode()).decode()}}}


class SourceTests(unittest.TestCase):
    def read(self, name): return (FIX / name).read_text()

    def test_official_list_profile_links_and_picker(self):
        operators, pages = parse_list_page(self.read("list_first_page.txt"))
        self.assertEqual(operators, ["g1" + "q" * 38])
        self.assertEqual(pages, ("?page=2",))
        self.assertNotIn("demo/profile", repr(operators))

    def test_duplicate_deterministic_and_external_ignored(self):
        row = " * [A](/r/gnops/valopers:g1" + "a" * 38 + ")"
        operators, _ = parse_list_page(row + "\n" + row + "\n[X](https://example.org/g1bad)")
        self.assertEqual(operators, ["g1" + "a" * 38])

    def test_wrong_or_malformed_realm_link_rejected(self):
        with self.assertRaises(ProfileSourceError):
            parse_list_page("[A](/r/gnops/valopers/not-a-render-path)")

    def test_detail_uses_heading_multiline_description_and_exact_metadata(self):
        operator = "g1" + "q" * 38
        profile = parse_detail(self.read("detail_ed25519.txt"), operator, 42)
        self.assertEqual(profile.moniker, "alpha-node")
        self.assertEqual(profile.description, "Runs public infrastructure.\n\nSecond description paragraph.")
        self.assertEqual(profile.source_signing_address, "g1" + "s" * 38)
        self.assertEqual(profile.server_type, "data-center")
        self.assertIsNone(profile.keep_running)
        self.assertNotIn("Profile link", profile.description)

    def test_detail_required_fields_operator_crosscheck_and_bounds(self):
        text = self.read("detail_ed25519.txt")
        operator = "g1" + "q" * 38
        for field in ("Operator Address", "Signing Address", "Signing PubKey", "Server Type"):
            malformed = "\n".join(line for line in text.splitlines() if field not in line)
            with self.subTest(field=field), self.assertRaises(ProfileSourceError): parse_detail(malformed, operator, 1)
        with self.assertRaises(ProfileSourceError): parse_detail(text, "g1" + "x" * 38, 1)
        with self.assertRaises(ProfileSourceError): parse_detail(text.replace("data-center", "garage"), operator, 1)
        with self.assertRaises(ProfileSourceError): parse_detail(text.replace("alpha-node", "x" * 33), operator, 1)

    def test_unknown_metadata_does_not_break_detail(self):
        text = self.read("detail_ed25519.txt").replace("- Server Type:", "- Region: earth\n- Server Type:")
        self.assertEqual(parse_detail(text, "g1" + "q" * 38, 1).server_type, "data-center")

    def test_query_json_encodes_string_params_and_pins_height(self):
        class Client:
            def get(self, method, **params):
                self.call = method, params
                return response("ok", 42)
        client = Client(); query_render(client, "", 42)
        method, params = client.call
        self.assertEqual(method, "abci_query")
        self.assertEqual(params["path"], json.dumps("vm/qrender"))
        self.assertEqual(params["data"], json.dumps("gno.land/r/gnops/valopers:"))
        self.assertEqual(params["height"], 42)
        query_render(client, "g1" + "q" * 38, 42)
        self.assertEqual(client.call[1]["data"], json.dumps("gno.land/r/gnops/valopers:g1" + "q" * 38))
        query_render(client, "?page=2", 42)
        self.assertEqual(client.call[1]["data"], json.dumps("gno.land/r/gnops/valopers:?page=2"))

    def test_vm_response_height_and_payload_validation(self):
        self.assertEqual(decode_vm_response(response("x", 42), 42).text, "x")
        with self.assertRaises(ProfileSourceError): decode_vm_response(response("x", 41), 42)
        with self.assertRaises(ProfileSourceError): decode_vm_response({"result":{"response":{"height":"42","value":"!"}}}, 42)
        with self.assertRaises(ProfileSourceError): decode_vm_response({}, 42)

    def test_crawl_pagination_all_at_one_height_and_dedup(self):
        pages = {"": self.read("list_first_page.txt"), "?page=2": self.read("list_next_page.txt"),
                 "g1"+"q"*38: self.read("detail_ed25519.txt"), "g1"+"p"*38: self.read("detail_secp256k1.txt")}
        calls = []
        def query(client, path, height): calls.append((path, height)); return SourceResponse(pages[path], height)
        result = collect_profiles(None, 42, query=query)
        self.assertEqual(len(result.profiles), 2)
        self.assertTrue(all(height == 42 for _, height in calls))
        self.assertEqual([p.operator_address for p in result.profiles], sorted(p.operator_address for p in result.profiles))

    def test_second_page_and_detail_height_mismatch_abort(self):
        pages = {"": self.read("list_first_page.txt"), "?page=2": self.read("list_next_page.txt")}
        def mismatch_page(client, path, height):
            if path == "?page=2": raise ProfileSourceError("mismatch")
            return SourceResponse(pages[path], height)
        with self.assertRaises(ProfileSourceError): collect_profiles(None, 42, query=mismatch_page)
        pages["g1"+"q"*38] = self.read("detail_ed25519.txt")
        pages["g1"+"p"*38] = self.read("detail_secp256k1.txt")
        def mismatch_detail(client, path, height):
            if path.startswith("g1"): raise ProfileSourceError("mismatch")
            return SourceResponse(pages[path], height)
        with self.assertRaises(ProfileSourceError): collect_profiles(None, 42, query=mismatch_detail)

    def test_page_profile_and_response_limits(self):
        with self.assertRaises(ProfileSourceError): parse_list_page("x" * (MAX_RESPONSE_BYTES + 1))
        def endless(client, path, height):
            page = int(path.split("=")[1]) if path else 1
            next_page = page + 1
            return SourceResponse(f"[A](/r/gnops/valopers:g1{'a'*40})\n[{next_page}](/r/gnops/valopers:?page={next_page})", height)
        with self.assertRaises(ProfileSourceError): collect_profiles(None, 1, query=endless)
        rows = "\n".join(f"[A](/r/gnops/valopers:g1{i:040d})" for i in range(MAX_PROFILES + 1))
        with self.assertRaises(ProfileSourceError): collect_profiles(None, 1, query=lambda *args: SourceResponse(rows, 1))


class PublicKeyTests(unittest.TestCase):
    def test_fixed_ed25519_and_secp256k1_vectors(self):
        self.assertEqual(normalize_gpub(ED_GPUB), ("/tm.PubKeyEd25519", base64.b64encode(bytes(range(1,33))).decode()))
        self.assertEqual(normalize_gpub(SEC_GPUB), ("/tm.PubKeySecp256k1", base64.b64encode(bytes(range(1,34))).decode()))

    def test_checksum_hrp_mixed_case_truncation_and_character_fail_closed(self):
        bad = [ED_GPUB[:-1]+("q" if ED_GPUB[-1] != "q" else "p"), "xpub"+ED_GPUB[4:], ED_GPUB[:8].upper()+ED_GPUB[8:], ED_GPUB[:-10], ED_GPUB[:20]+"!"+ED_GPUB[21:]]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_gpub(value)

    def test_invalid_amino_forms_do_not_match(self):
        profile = parse_detail((FIX/"detail_ed25519.txt").read_text(), "g1"+"q"*38, 1)
        invalid = replace(profile, consensus_pubkey="bad")
        result = match_profiles([invalid], [(profile.source_signing_address, "/tm.PubKeyEd25519", base64.b64encode(bytes(range(1,33))).decode())])
        self.assertEqual(result[0].match_status, "invalid_pubkey")
        self.assertIsNone(result[0].signing_address)


class MatchingTests(unittest.TestCase):
    def profiles(self):
        return (parse_detail((FIX/"detail_ed25519.txt").read_text(), "g1"+"q"*38, 1),
                parse_detail((FIX/"detail_secp256k1.txt").read_text(), "g1"+"p"*38, 1))

    def test_exact_unmatched_invalid_ambiguous_and_order(self):
        alpha, beta = self.profiles(); typ, val = normalize_gpub(alpha.consensus_pubkey)
        invalid = replace(alpha, operator_address="g1"+"i"*38, consensus_pubkey="bad")
        got = match_profiles([beta, invalid, alpha], [(alpha.source_signing_address, typ, val)])
        self.assertEqual([p.match_status for p in got], ["invalid_pubkey", "unmatched", "matched"])
        duplicate = replace(alpha, operator_address="g1"+"z"*38)
        self.assertEqual({p.match_status for p in match_profiles([alpha, duplicate], [])}, {"ambiguous"})

    def test_source_signing_crosscheck_aborts(self):
        alpha, _ = self.profiles(); typ, val = normalize_gpub(alpha.consensus_pubkey)
        with self.assertRaises(ProfileSourceError): match_profiles([alpha], [("g1"+"x"*38, typ, val)])


class FakeCursor:
    def __init__(self, rows=(), lock=True, fail_batch=False):
        self.rows=list(rows); self.lock=lock; self.fail_batch=fail_batch; self.executed=[]; self.batches=[]
    def execute(self, sql, params=None): self.executed.append((sql, params))
    def fetchall(self): return self.rows
    def fetchone(self): return (self.lock,)
    def executemany(self, sql, rows):
        self.batches.append((sql, list(rows)))
        if self.fail_batch: raise RuntimeError("batch failed")
    def __enter__(self): return self
    def __exit__(self, *args): return False

class FakeConnection:
    def __init__(self, cursor): self.cursor_obj=cursor; self.commits=0
    def cursor(self): return self.cursor_obj
    def commit(self): self.commits += 1
    def __enter__(self): return self
    def __exit__(self, *args): return False

class DatabaseTests(unittest.TestCase):
    def profile(self): return MatchingTests().profiles()[0]
    def database(self, connection):
        db=PostgresDatabase("postgresql://user:secret@host/db"); db.connect=lambda: connection; return db

    def test_one_validator_select_and_no_n_plus_one(self):
        cursor=FakeCursor([("S","T","V")]); got=self.database(FakeConnection(cursor)).load_validator_keys()
        self.assertEqual(got, [("S","T","V")]); self.assertEqual(len(cursor.executed), 1)

    def test_batch_transaction_lock_and_sql_semantics(self):
        cursor=FakeCursor(); connection=FakeConnection(cursor); db=self.database(connection)
        self.assertEqual(db.upsert_validator_profiles([self.profile(), self.profile()]), 2)
        self.assertEqual(connection.commits, 1); self.assertEqual(len(cursor.batches[0][1]), 2)
        sql=cursor.batches[0][0]
        self.assertIn("pg_try_advisory_xact_lock", cursor.executed[0][0])
        self.assertIn("updated_at = now()", sql); self.assertNotIn("inserted_at =", sql)
        self.assertNotIn("DELETE", sql.upper()); self.assertNotIn("TRUNCATE", sql.upper())

    def test_lock_contention_no_batch_or_commit(self):
        cursor=FakeCursor(lock=False); connection=FakeConnection(cursor)
        with self.assertRaises(DatabaseError): self.database(connection).upsert_validator_profiles([self.profile()])
        self.assertFalse(cursor.batches); self.assertEqual(connection.commits, 0)

    def test_batch_failure_no_commit_and_empty_batch_no_connection(self):
        cursor=FakeCursor(fail_batch=True); connection=FakeConnection(cursor)
        with self.assertRaisesRegex(RuntimeError, "batch failed"): self.database(connection).upsert_validator_profiles([self.profile()])
        self.assertEqual(connection.commits, 0)
        db=PostgresDatabase("secret"); db.connect=lambda: self.fail("must not connect")
        self.assertEqual(db.upsert_validator_profiles([]), 0)


class CliTests(unittest.TestCase):
    def selected(self): return type("Selected", (), {"latest_height":42, "client":object()})()
    def profile(self): return MatchingTests().profiles()[0]

    def test_dry_run_reads_database_and_never_upserts(self):
        db=unittest.mock.Mock(); typ,val=normalize_gpub(self.profile().consensus_pubkey)
        db.load_validator_keys.return_value=[(self.profile().source_signing_address,typ,val)]
        out=io.StringIO()
        with patch("scripts.sync_validator_profiles.load_config", return_value=type("C",(),{"rpc_urls":["safe"],"chain_id":"test-13","max_height_lag":1,"database_url":"safe"})()), patch("scripts.sync_validator_profiles.select_rpc", return_value=self.selected()), patch("scripts.sync_validator_profiles.collect_profiles", return_value=type("R",(),{"profiles":(self.profile(),)})()), patch("scripts.sync_validator_profiles.PostgresDatabase", return_value=db), contextlib.redirect_stdout(out):
            self.assertEqual(sync_validator_profiles.main(["--dry-run"]), 0)
        db.load_validator_keys.assert_called_once(); db.upsert_validator_profiles.assert_not_called()
        self.assertIn("Matched: 1", out.getvalue()); self.assertIn("Database writes: 0", out.getvalue())

    def test_write_upserts_once_and_source_failure_does_not_touch_database(self):
        db=unittest.mock.Mock(); db.load_validator_keys.return_value=[]; db.upsert_validator_profiles.return_value=1
        common=(patch("scripts.sync_validator_profiles.load_config", return_value=type("C",(),{"rpc_urls":["safe"],"chain_id":"test-13","max_height_lag":1,"database_url":"safe"})()), patch("scripts.sync_validator_profiles.select_rpc", return_value=self.selected()), patch("scripts.sync_validator_profiles.PostgresDatabase", return_value=db))
        with common[0], common[1], common[2], patch("scripts.sync_validator_profiles.collect_profiles", return_value=type("R",(),{"profiles":(self.profile(),)})):
            self.assertEqual(sync_validator_profiles.main([]), 0)
        db.upsert_validator_profiles.assert_called_once()
        db.reset_mock()
        with patch("scripts.sync_validator_profiles.load_config", side_effect=RuntimeError("https://user:password@host/?token=secret")), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(sync_validator_profiles.main([]), 1)
        self.assertNotIn("password", err.getvalue()); self.assertNotIn("secret", err.getvalue())
        db.upsert_validator_profiles.assert_not_called()


class SchemaTests(unittest.TestCase):
    def snapshot(self):
        return {
            "tables": set(init_database.EXPECTED_TABLES),
            "columns": copy.deepcopy(init_database.EXPECTED_COLUMNS),
            "primary_keys": copy.deepcopy(init_database.EXPECTED_PRIMARY_KEYS),
            "unique_constraints": set(init_database.EXPECTED_UNIQUES),
            "foreign_keys": set(init_database.EXPECTED_FOREIGN_KEYS),
            "check_constraints": dict(init_database.EXPECTED_CHECKS),
            "indexes": dict(init_database.EXPECTED_INDEXES),
        }

    def legacy(self):
        snapshot = self.snapshot(); snapshot["tables"].remove("validator_profiles")
        snapshot["columns"].pop("validator_profiles"); snapshot["primary_keys"].pop("validator_profiles")
        snapshot["foreign_keys"] = {item for item in snapshot["foreign_keys"] if item[0] != "validator_profiles"}
        snapshot["check_constraints"] = {key:value for key,value in snapshot["check_constraints"].items() if not key.startswith("validator_profiles_")}
        snapshot["indexes"] = {key:value for key,value in snapshot["indexes"].items() if not key.startswith("validator_profiles_")}
        return snapshot

    def test_schema_upgrade_and_constraints_are_tracked(self):
        schema=(Path(__file__).parents[1]/"database/schema.sql").read_text()
        upgrade=(Path(__file__).parents[1]/"database/upgrades/001_validator_profiles.sql").read_text()
        self.assertIn("profile_hash ~ '^[0-9a-f]{64}$'", schema)
        self.assertIn("normalized_public_key_type IS NULL", schema)
        self.assertIn("lower(moniker)", upgrade)
        self.assertNotIn("CREATE TABLE blocks", upgrade)

    def test_exact_legacy_accepted_but_incompatible_rejected(self):
        init_database.validate_legacy_schema_snapshot(self.legacy())
        broken = self.legacy(); broken["columns"]["validators"].pop("public_key_value")
        with self.assertRaises(init_database.SchemaCompatibilityError):
            init_database.validate_legacy_schema_snapshot(broken)

    def test_legacy_upgrade_is_additive_and_validated_before_commit(self):
        class Cursor:
            def __init__(self): self.sql=[]
            def execute(self, sql): self.sql.append(sql)
            def fetchall(self): return [("blocks",)]
            def __enter__(self): return self
            def __exit__(self,*args): return False
        class Connection:
            def __init__(self): self.cursor_obj=Cursor(); self.commits=0
            def cursor(self): return self.cursor_obj
            def commit(self): self.commits += 1
            def __enter__(self): return self
            def __exit__(self,*args): return False
        connection=Connection()
        with patch("scripts.init_database.fetch_schema_snapshot", side_effect=[self.legacy(), self.snapshot()]):
            init_database.initialize_or_validate("postgresql://safe", connect=lambda _: connection)
        self.assertEqual(connection.commits, 1)
        ddl="\n".join(connection.cursor_obj.sql)
        self.assertIn("CREATE TABLE validator_profiles", ddl)
        self.assertNotIn("CREATE TABLE blocks", ddl)

    def test_functional_index_introspection_uses_pg_get_indexdef(self):
        class Cursor:
            calls=[]
            def execute(self, sql): self.calls.append(sql)
            def fetchall(self): return []
        init_database.fetch_schema_snapshot(Cursor())
        self.assertIn("pg_get_indexdef", Cursor.calls[3])
        self.assertNotIn("keys.attnum <> 0", Cursor.calls[3])

if __name__ == "__main__": unittest.main()
