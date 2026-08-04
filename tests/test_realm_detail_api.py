from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.app as module
from api.config import ApiConfig

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)
ADDR = "g1" + "q" * 38
HASH = "a" * 64


def catalog_row(path="gno.land/r/gnoswap/app", kind="realm", calls=2, success=1, failed=1, unknown=0,
                height=9, tx_index=1, at=NOW):
    return {"chain_id":"topaz-1","path":path,"path_kind":kind,"rpc_visible":True,"deployer_address":ADDR,
        "deploy_height":2,"deploy_tx_index":0,"first_seen_height":2,"last_activity_height":height,
        "last_activity_tx_index":tx_index,"last_activity_at":at,"call_count":calls,
        "successful_call_count":success,"failed_call_count":failed,"unknown_result_call_count":unknown}


_DEFAULT_CALL_CHAIN = object()


def source_row(indexed=10, call_from=1, call_through=10, chain="topaz-1", call_chain=_DEFAULT_CALL_CHAIN):
    if call_chain is _DEFAULT_CALL_CHAIN:
        call_chain = None if call_from is None and call_through is None else chain
    return {"chain_id":chain,"indexed_height":indexed,"observed_height":8,"refreshed_at":NOW,
        "activity_from_height":1,"activity_through_height":9,"call_chain_id":call_chain,
        "call_index_from_height":call_from,"call_index_through_height":call_through}


class RealmDetailApiTests(unittest.TestCase):
    def setUp(self): module.app.state.api_config = SimpleNamespace(chain_id="topaz-1")

    def test_detail_accepts_realm_and_curated_metadata(self):
        result = {"source":source_row(),"item":catalog_row()}
        with patch.object(module.database, "fetch_realm_detail", return_value=result):
            response = module.get_realm_detail(path="gno.land/r/gnoswap/app")
        self.assertEqual(response.namespace_key, "gnoswap")
        self.assertEqual(response.application.display_name, "GnoSwap")
        self.assertTrue(response.source.call_index_complete)

    def test_detail_accepts_package_without_namespace_or_application(self):
        result = {"source":source_row(call_from=None, call_through=None),
                  "item":catalog_row(path="gno.land/p/demo/pkg", kind="package", calls=0, success=0, failed=0, unknown=0,
                                      height=None, tx_index=None, at=None)}
        with patch.object(module.database, "fetch_realm_detail", return_value=result):
            response = module.get_realm_detail(path="gno.land/p/demo/pkg")
        self.assertIsNone(response.namespace_key)
        self.assertIsNone(response.application)
        self.assertFalse(response.source.call_index_complete)

    def test_detail_validation_and_unavailable_cases(self):
        for path in ("bad", " gno.land/r/a", "gno.land/r/a "):
            with self.subTest(path=path), self.assertRaises(HTTPException) as raised:
                module.get_realm_detail(path=path)
            self.assertEqual(raised.exception.status_code, 422)
        with patch.object(module.database, "fetch_realm_detail", return_value={"source":source_row(),"item":None}):
            with self.assertRaises(HTTPException) as raised: module.get_realm_detail(path="gno.land/r/missing")
        self.assertEqual(raised.exception.status_code, 404)
        bad = {"source":source_row(),"item":catalog_row(calls=3, success=1, failed=1, unknown=0)}
        with patch.object(module.database, "fetch_realm_detail", return_value=bad):
            with self.assertRaises(HTTPException) as raised: module.get_realm_detail(path="gno.land/r/gnoswap/app")
        self.assertEqual(raised.exception.status_code, 503)

    def test_call_coverage_complete_only_at_checkpoint(self):
        for indexed, through, expected in ((10,10,True),(10,9,False),(10,11,False)):
            result={"source":source_row(indexed=indexed, call_through=through),"item":catalog_row()}
            with self.subTest(through=through), patch.object(module.database, "fetch_realm_detail", return_value=result):
                self.assertEqual(module.get_realm_detail(path="gno.land/r/gnoswap/app").source.call_index_complete, expected)


class RealmCallsApiTests(unittest.TestCase):
    def setUp(self): module.app.state.api_config = SimpleNamespace(chain_id="topaz-1")

    def call_row(self, h=10, tx=2, msg=1, hash_value=HASH):
        return {"block_height":h,"tx_index":tx,"message_index":msg,"caller_address":ADDR,
            "function_name":"Render","args_count":0,"send_amount":"1ugnot","tx_hash_hex":hash_value,
            "time_utc":NOW,"execution_status":"success","gas_wanted":"10","gas_used":"7"}

    def result(self, rows):
        return {"source":source_row(),"item":catalog_row(),"items":rows,"coverage_available":True}

    def test_calls_defaults_limit_plus_one_pagination_and_hash_normalization(self):
        rows=[self.call_row(10,2,1), self.call_row(10,2,0), self.call_row(9,5,0)]
        with patch.object(module.database, "fetch_realm_calls", return_value=self.result(rows)) as fetch:
            response = module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=2)
        self.assertEqual(fetch.call_args.kwargs["limit"], 2)
        self.assertEqual([item.message_index for item in response.items], [1,0])
        self.assertEqual(response.items[0].tx_hash, HASH.upper())
        self.assertEqual((response.pagination.next_before_height, response.pagination.next_before_tx_index,
                          response.pagination.next_before_message_index), (10,2,0))

    def test_calls_validation_unknown_and_unavailable(self):
        with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/p/demo/pkg")
        self.assertEqual((raised.exception.status_code, raised.exception.detail), (422, "Realm calls require a gno.land/r/... path"))
        with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/app", before_height=2, before_tx_index=None, before_message_index=None)
        self.assertEqual(raised.exception.status_code, 422)
        with patch.object(module.database, "fetch_realm_calls", return_value=None):
            with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/missing")
        self.assertEqual(raised.exception.status_code, 404)
        unavailable={"source":source_row(call_from=None, call_through=None),"item":catalog_row(),"items":[],"coverage_available":False}
        with patch.object(module.database, "fetch_realm_calls", return_value=unavailable):
            with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
        self.assertEqual((raised.exception.status_code, raised.exception.detail), (409, module.CALLS_UNAVAILABLE_DETAIL))


    def test_internal_coverage_available_contract_is_strict(self):
        base={"source":source_row(),"item":catalog_row(),"items":[]}
        with patch.object(module.database, "fetch_realm_calls", return_value=base | {"coverage_available":True}):
            self.assertEqual(module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None).items, [])
        with patch.object(module.database, "fetch_realm_calls", return_value=base | {"coverage_available":False}):
            with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
            self.assertEqual((raised.exception.status_code, raised.exception.detail), (409, module.CALLS_UNAVAILABLE_DETAIL))
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value), patch.object(module.database, "fetch_realm_calls", return_value=base | {"coverage_available":value}):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
                self.assertEqual(raised.exception.status_code, 503)
        with patch.object(module.database, "fetch_realm_calls", return_value=base):
            with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
            self.assertEqual(raised.exception.status_code, 503)

    def test_calls_fail_closed_for_duplicate_or_non_descending_rows(self):
        for rows in ([self.call_row(10,1,0), self.call_row(10,1,0)], [self.call_row(9,1,0), self.call_row(10,1,0)]):
            with self.subTest(rows=rows), patch.object(module.database, "fetch_realm_calls", return_value=self.result(rows)):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
            self.assertEqual(raised.exception.status_code, 503)


    def test_malformed_call_scalars_fail_closed(self):
        variants=[]
        for key, value in (("function_name", ""), ("function_name", " x"), ("function_name", "x" * 161),
                           ("function_name", "bad\n"), ("send_amount", ""), ("send_amount", " x"),
                           ("send_amount", "x" * 161), ("send_amount", "bad\n"), ("args_count", True),
                           ("args_count", "1"), ("args_count", -1), ("args_count", 100001),
                           ("block_height", "10"), ("tx_index", False), ("message_index", "0")):
            row = self.call_row()
            row[key] = value
            variants.append(row)
        for row in variants:
            with self.subTest(row=row), patch.object(module.database, "fetch_realm_calls", return_value=self.result([row])):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
                self.assertEqual(raised.exception.status_code, 503)
        row = self.call_row(); row["function_name"] = None; row["send_amount"] = None; row["args_count"] = None
        with patch.object(module.database, "fetch_realm_calls", return_value=self.result([row])):
            item = module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None).items[0]
        self.assertIsNone(item.function_name); self.assertIsNone(item.send_amount); self.assertIsNone(item.args_count)

class RealmDetailDatabaseSqlTests(unittest.TestCase):
    def test_calls_sql_uses_tuple_cursor_limit_and_no_payload_summary(self):
        from api.database import REALM_CALLS_PAGE_SQL
        normalized = " ".join(REALM_CALLS_PAGE_SQL.split())
        self.assertIn("( call.block_height, call.tx_index, call.message_index ) < ( %s::bigint, %s::integer, %s::integer )", normalized)
        self.assertIn("AND call.block_height >= %s::bigint AND call.block_height <= %s::bigint", normalized)
        self.assertIn("ORDER BY call.block_height DESC, call.tx_index DESC, call.message_index DESC LIMIT %s", normalized)
        self.assertNotIn("payload_summary", REALM_CALLS_PAGE_SQL)
        self.assertNotIn("OFFSET", REALM_CALLS_PAGE_SQL.upper())

    def test_database_coverage_helper_rules(self):
        from api.database import complete_realm_call_coverage_bounds
        self.assertIsNone(complete_realm_call_coverage_bounds(source_row(call_from=None, call_through=None) | {"call_chain_id":None}, "topaz-1"))
        self.assertEqual(complete_realm_call_coverage_bounds(source_row(), "topaz-1"), (1, 10))
        self.assertIsNone(complete_realm_call_coverage_bounds(source_row(call_through=9), "topaz-1"))
        self.assertIsNone(complete_realm_call_coverage_bounds(source_row(call_through=11), "topaz-1"))
        for source in (source_row(call_from=None), source_row() | {"call_chain_id":None}, source_row(chain="other-chain", call_chain="other-chain"), source_row(chain="other-chain", call_from=None, call_through=None)):
            with self.subTest(source=source), self.assertRaises(ValueError):
                complete_realm_call_coverage_bounds(source, "topaz-1")

    def test_database_detail_and_calls_use_one_repeatable_read_snapshot(self):
        from api.database import ApiDatabase, REALM_CALLS_PAGE_SQL, REALM_DETAIL_ITEM_SQL, REALM_DETAIL_SOURCE_SQL
        statements=[]
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*_args): return False
            def execute(self,sql,params=None): statements.append((sql,params))
            def fetchone(self):
                sql=statements[-1][0]
                if sql == REALM_DETAIL_ITEM_SQL: return catalog_row()
                if sql == REALM_DETAIL_SOURCE_SQL: return source_row()
                return None
            def fetchall(self): return []
        class Context:
            def __init__(self,value): self.value=value
            def __enter__(self): return self.value
            def __exit__(self,*_args): return False
        class Connection:
            def transaction(self): return Context(None)
            def cursor(self): return Cursor()
        database = ApiDatabase(); database.pool = SimpleNamespace(connection=lambda **_kwargs: Context(Connection()))
        detail = database.fetch_realm_detail(chain_id="topaz-1", path="gno.land/r/gnoswap/app")
        calls = database.fetch_realm_calls(chain_id="topaz-1", path="gno.land/r/gnoswap/app", limit=25,
            before_height=None, before_tx_index=None, before_message_index=None)
        self.assertEqual(detail["item"]["path"], "gno.land/r/gnoswap/app")
        self.assertEqual(calls["items"], [])
        self.assertEqual(statements[0], ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY", None))
        second_set = [index for index, (sql, _params) in enumerate(statements) if sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
        self.assertEqual(second_set, [0, 3])
        self.assertIn((REALM_CALLS_PAGE_SQL, ("topaz-1", "gno.land/r/gnoswap/app", 1, 10, None, None, None, None, 26)), statements)


class RealmCoverageAndSentinelTests(unittest.TestCase):
    def setUp(self): module.app.state.api_config = SimpleNamespace(chain_id="topaz-1")

    def test_unavailable_coverage_states_do_not_execute_page_query(self):
        from api.database import ApiDatabase, REALM_CALLS_PAGE_SQL, REALM_DETAIL_ITEM_SQL, REALM_DETAIL_SOURCE_SQL
        for source in (source_row(call_from=None, call_through=None, chain=None) | {"chain_id":"topaz-1", "call_chain_id":None},
                       source_row(indexed=10, call_through=9), source_row(indexed=10, call_through=11)):
            statements=[]
            class Cursor:
                def __enter__(self): return self
                def __exit__(self,*_args): return False
                def execute(self,sql,params=None): statements.append((sql,params))
                def fetchone(self): return catalog_row() if statements[-1][0] == REALM_DETAIL_ITEM_SQL else source
                def fetchall(self): raise AssertionError("page query must not execute")
            class Context:
                def __init__(self,value): self.value=value
                def __enter__(self): return self.value
                def __exit__(self,*_args): return False
            class Connection:
                def transaction(self): return Context(None)
                def cursor(self): return Cursor()
            database=ApiDatabase(); database.pool=SimpleNamespace(connection=lambda **_kwargs:Context(Connection()))
            result=database.fetch_realm_calls(chain_id="topaz-1", path="gno.land/r/gnoswap/app", limit=25,
                before_height=None, before_tx_index=None, before_message_index=None)
            self.assertFalse(result["coverage_available"])
            self.assertFalse(any(sql == REALM_CALLS_PAGE_SQL for sql, _params in statements))

    def test_malformed_coverage_state_becomes_503(self):
        variants=[source_row(call_from=None), source_row(chain="other-chain", call_chain="other-chain"), source_row() | {"call_chain_id":None}]
        for source in variants:
            with self.subTest(source=source), patch.object(module.database, "fetch_realm_calls",
                    return_value={"source":source,"item":catalog_row(),"items":[],"coverage_available":True}):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
                self.assertEqual(raised.exception.status_code, 503)

    def test_sentinel_rows_are_validated_before_pagination_split(self):
        valid=[RealmCallsApiTests().call_row(10,2,1), RealmCallsApiTests().call_row(10,2,0)]
        with patch.object(module.database, "fetch_realm_calls", return_value={"source":source_row(),"item":catalog_row(),"items":valid,"coverage_available":True}):
            response=module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=1)
        self.assertEqual((response.pagination.next_before_height, response.pagination.next_before_tx_index,
                          response.pagination.next_before_message_index), (10,2,1))
        cases=[valid[:1]+[RealmCallsApiTests().call_row(10,2,1)],
               valid[:1]+[RealmCallsApiTests().call_row(11,0,0)],
               valid[:1]+[RealmCallsApiTests().call_row(10,2,0, hash_value="bad")],
               valid+[RealmCallsApiTests().call_row(9,0,0)]]
        for rows in cases:
            with self.subTest(rows=rows), patch.object(module.database, "fetch_realm_calls",
                    return_value={"source":source_row(),"item":catalog_row(),"items":rows,"coverage_available":True}):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=1)
                self.assertEqual(raised.exception.status_code, 503)
        with patch.object(module.database, "fetch_realm_calls", return_value={"source":source_row(),"item":catalog_row(),"items":valid[:1],"coverage_available":True}):
            self.assertIsNone(module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=1).pagination.next_before_height)

    def test_rows_outside_source_coverage_fail_closed(self):
        for row in (RealmCallsApiTests().call_row(1,0,0), RealmCallsApiTests().call_row(11,0,0)):
            with self.subTest(row=row), patch.object(module.database, "fetch_realm_calls",
                    return_value={"source":source_row(call_from=2, call_through=10),"item":catalog_row(),"items":[row],"coverage_available":True}):
                with self.assertRaises(HTTPException) as raised: module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None)
                self.assertEqual(raised.exception.status_code, 503)
        for row in (RealmCallsApiTests().call_row(2,0,0), RealmCallsApiTests().call_row(10,0,0)):
            with self.subTest(boundary=row), patch.object(module.database, "fetch_realm_calls",
                    return_value={"source":source_row(call_from=2, call_through=10),"item":catalog_row(),"items":[row],"coverage_available":True}):
                self.assertEqual(len(module.get_realm_calls(path="gno.land/r/gnoswap/app", limit=25, before_height=None, before_tx_index=None, before_message_index=None).items), 1)

    def test_catalog_activity_and_deploy_semantics(self):
        accepted={"source":source_row(),"item":catalog_row()}
        with patch.object(module.database, "fetch_realm_detail", return_value=accepted):
            self.assertEqual(module.get_realm_detail(path="gno.land/r/gnoswap/app").item.call_count, 2)
        variants=[catalog_row(path="gno.land/p/demo/pkg", kind="package"),
                  catalog_row(path="gno.land/p/demo/pkg", kind="package", calls=0, success=0, failed=0, unknown=0),
                  catalog_row(calls=0, success=0, failed=0, unknown=0),
                  catalog_row(height=None),
                  catalog_row() | {"deploy_tx_index":None},
                  catalog_row() | {"deploy_height":0},
                  catalog_row() | {"deploy_tx_index":-1},
                  catalog_row() | {"first_seen_height":0}]
        for item in variants:
            with self.subTest(item=item), patch.object(module.database, "fetch_realm_detail", return_value={"source":source_row(),"item":item}):
                with self.assertRaises(HTTPException) as raised: module.get_realm_detail(path=item["path"])
                self.assertEqual(raised.exception.status_code, 503)

    def test_schema_validators_reject_partial_ranges_and_cursors(self):
        from pydantic import ValidationError
        from api.schemas import RealmCallsPagination, RealmDetailSource
        with self.assertRaises(ValidationError): RealmCallsPagination(limit=25, next_before_height=1)
        with self.assertRaises(ValidationError): RealmDetailSource(chain_id="topaz-1", indexed_height=10,
            catalog_observed_height=1, catalog_refreshed_at="2026-08-04T00:00:00Z", activity_from_height=1,
            activity_through_height=None, call_index_from_height=None, call_index_through_height=None,
            call_index_complete=False)
        with self.assertRaises(ValidationError): RealmDetailSource(chain_id="topaz-1", indexed_height=10,
            catalog_observed_height=1, catalog_refreshed_at="2026-08-04T00:00:00Z", activity_from_height=None,
            activity_through_height=None, call_index_from_height=1, call_index_through_height=None,
            call_index_complete=False)
        with self.assertRaises(ValidationError): RealmDetailSource(chain_id="topaz-1", indexed_height=10,
            catalog_observed_height=1, catalog_refreshed_at="2026-08-04T00:00:00Z", activity_from_height=None,
            activity_through_height=None, call_index_from_height=None, call_index_through_height=None,
            call_index_complete=True)

        from api.schemas import RealmCallSource
        with self.assertRaises(ValidationError): RealmCallSource(chain_id="topaz-1", path="gno.land/r/a", indexed_height=10, from_height=5, through_height=4)
        with self.assertRaises(ValidationError): RealmCallSource(chain_id="topaz-1", path="gno.land/r/a", indexed_height=10, from_height=1, through_height=9)
        with self.assertRaises(ValidationError): RealmCallSource(chain_id="topaz-1", path="gno.land/r/a", indexed_height=10, from_height=1, through_height=11)
        self.assertEqual(RealmCallSource(chain_id="topaz-1", path="gno.land/r/a", indexed_height=10, from_height=1, through_height=10).through_height, 10)


class RealmDetailHttpContractTests(unittest.TestCase):
    def client(self, fake_database):
        config = ApiConfig(database_url="postgresql://test:password@localhost/test", chain_id="topaz-1")
        return patch.object(module, "database", fake_database), patch.object(module, "load_config", return_value=config)

    def test_calls_http_parameter_contracts(self):
        outer = self
        class FakeDatabase:
            def __init__(self): self.calls=[]
            def open(self, _config): pass
            def close(self): pass
            def fetch_realm_calls(self, **kwargs):
                self.calls.append(kwargs)
                return {"source":source_row(),"item":catalog_row(),"items":[],"coverage_available":True}
        fake = FakeDatabase()
        config = ApiConfig(database_url="postgresql://test:password@localhost/test", chain_id="topaz-1")
        with patch.object(module, "database", fake), patch.object(module, "load_config", return_value=config), TestClient(module.app) as client:
            self.assertEqual(client.get("/api/realms/calls?path=gno.land/r/gnoswap/app").status_code, 200)
            self.assertEqual(fake.calls[-1]["limit"], 25)
            self.assertEqual(client.get("/api/realms/calls?path=gno.land/r/gnoswap/app&limit=100").status_code, 200)
            self.assertEqual(fake.calls[-1]["limit"], 100)
            for url in ("/api/realms/calls?path=gno.land/r/gnoswap/app&limit=101",
                        "/api/realms/calls?path=gno.land/r/gnoswap/app&before_height=2",
                        "/api/realms/calls?path=bad",
                        "/api/realms/calls?path=gno.land/p/demo/pkg"):
                self.assertEqual(client.get(url).status_code, 422, url)

    def test_calls_http_database_contracts(self):
        class FakeDatabase:
            def __init__(self, result): self.result=result
            def open(self, _config): pass
            def close(self): pass
            def fetch_realm_calls(self, **_kwargs): return self.result
        cases=[(None,404),
               ({"source":source_row(call_from=None, call_through=None),"item":catalog_row(),"items":[],"coverage_available":False},409),
               ({"source":source_row(),"item":catalog_row(),"items":[],"coverage_available":None},503)]
        config = ApiConfig(database_url="postgresql://test:password@localhost/test", chain_id="topaz-1")
        for result, status in cases:
            with self.subTest(status=status), patch.object(module, "database", FakeDatabase(result)), patch.object(module, "load_config", return_value=config), TestClient(module.app) as client:
                self.assertEqual(client.get("/api/realms/calls?path=gno.land/r/gnoswap/app").status_code, status)

    def test_detail_http_realm_package_and_malformed_source(self):
        class FakeDatabase:
            def __init__(self, result): self.result=result
            def open(self, _config): pass
            def close(self): pass
            def fetch_realm_detail(self, **_kwargs): return self.result
        config = ApiConfig(database_url="postgresql://test:password@localhost/test", chain_id="topaz-1")
        cases=[({"source":source_row(),"item":catalog_row()}, "gno.land/r/gnoswap/app", 200),
               ({"source":source_row(call_from=None, call_through=None),"item":catalog_row(path="gno.land/p/demo/pkg", kind="package", calls=0, success=0, failed=0, unknown=0, height=None, tx_index=None, at=None)}, "gno.land/p/demo/pkg", 200),
               ({"source":source_row(call_from=None, call_through=10),"item":catalog_row()}, "gno.land/r/gnoswap/app", 503)]
        for result, path, status in cases:
            with self.subTest(path=path), patch.object(module, "database", FakeDatabase(result)), patch.object(module, "load_config", return_value=config), TestClient(module.app) as client:
                self.assertEqual(client.get(f"/api/realms/detail?path={path}").status_code, status)
