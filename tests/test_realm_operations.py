"""Focused non-PostgreSQL contracts for Realm operator commands."""
import unittest
from scripts.rebuild_realm_activity import RebuildError, rebuild_cursor
from scripts.refresh_realm_catalog import RefreshStatus, fetch_realm_paths, persist_refresh

class Cursor:
    def __init__(self, responses):
        self.responses=list(responses); self.executed=[]; self.rowcount=1; self._one=None; self._all=[]
    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()),params))
        if "pg_advisory_xact_lock" in sql:
            self._one=None; self._all=[]; return
        response=self.responses.pop(0) if self.responses else None
        if isinstance(response,list): self._all=response; self._one=None
        else: self._one=response; self._all=[]
    def fetchone(self): return self._one
    def fetchall(self): return self._all

class RebuildSafetyTests(unittest.TestCase):
    def test_missing_state_fails_before_update(self):
        cursor=Cursor([None])
        with self.assertRaisesRegex(RebuildError,"refresh_realm_catalog.py"):
            rebuild_cursor(cursor,"topaz-1",1,2)
        self.assertFalse(any(sql.startswith("UPDATE") for sql,_ in cursor.executed))
    def test_incomplete_blocks_fail_before_transactions_or_update(self):
        cursor=Cursor([(1,),(10,),(1,1,1)])
        with self.assertRaisesRegex(RebuildError,"missing local blocks"):
            rebuild_cursor(cursor,"topaz-1",1,2)
        self.assertFalse(any(sql.startswith("UPDATE") for sql,_ in cursor.executed))
    def test_dry_run_valid_zero_transaction_range_changes_nothing(self):
        cursor=Cursor([(1,),(10,),(2,3,4),[]])
        self.assertEqual(rebuild_cursor(cursor,"topaz-1",3,4,True),0)
        self.assertFalse(any(sql.startswith("UPDATE") for sql,_ in cursor.executed))
    def test_dry_run_reports_unique_paths_across_heights(self):
        message={'parse_status':'parsed','messages':[{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]}
        rows=[(3,0,message,'success','t3'),(4,0,message,'failed','t4')]
        cursor=Cursor([(1,),(10,),(2,3,4),rows])
        self.assertEqual(rebuild_cursor(cursor,"topaz-1",3,4,True),1)
    def test_rebuild_skips_ambiguous_legacy_path(self):
        path='gno.land/r/'+('x'*(160-len('gno.land/r/')))
        message={'parse_status':'parsed','messages':[{'type':'gno.vm.MsgCall','package_path':path}]}
        cursor=Cursor([(1,),(10,),(1,3,3),[(3,0,message,'success','t3')]])
        self.assertEqual(rebuild_cursor(cursor,"topaz-1",3,3,True),0)

class RefreshQueryTests(unittest.TestCase):
    class Client:
        def __init__(self, payload):
            self.payload = payload
            self.calls = []

        def abci_query(self, path, data, height):
            self.calls.append((path, data, height))
            return self.payload

    def test_query_uses_bounded_gnoland_prefix(self):
        client = self.Client(
            "gno.land/p/demo/pkg\ngno.land/r/demo/realm"
        )

        paths = fetch_realm_paths(client, 123)

        self.assertEqual(
            client.calls,
            [("vm/qpaths?limit=10000", "gno.land/", 123)],
        )
        self.assertEqual(
            paths,
            (
                ("gno.land/p/demo/pkg", "package"),
                ("gno.land/r/demo/realm", "realm"),
            ),
        )

    def test_stdlib_response_is_rejected(self):
        client = self.Client("bufio")

        with self.assertRaisesRegex(ValueError, "qpaths_invalid_path"):
            fetch_realm_paths(client, 123)

        self.assertEqual(
            client.calls,
            [("vm/qpaths?limit=10000", "gno.land/", 123)],
        )


class RefreshPersistenceTests(unittest.TestCase):
    def test_invalid_set_is_rejected_before_visibility_update(self):
        cursor=Cursor([])
        with self.assertRaises(ValueError): persist_refresh(cursor,"topaz-1",5,None,[("bad","realm")])
        self.assertEqual(cursor.executed,[])
    def test_duplicate_set_is_rejected_before_visibility_update(self):
        cursor=Cursor([]); paths=[('gno.land/r/x','realm')]*2
        with self.assertRaises(ValueError): persist_refresh(cursor,"topaz-1",5,None,paths)
        self.assertEqual(cursor.executed,[])

    def test_initial_refresh_returns_counts(self):
        cursor = Cursor([None, None, None, None, (2,)])
        result = persist_refresh(cursor, "topaz-1", 5, 7, [
            ("gno.land/r/demo", "realm"),
            ("gno.land/p/demo", "package"),
        ])
        self.assertEqual(result.status, RefreshStatus.APPLIED)
        self.assertEqual((result.realm_count, result.package_count, result.total_count), (1, 1, 2))

    def test_equal_height_is_noop(self):
        cursor = Cursor([(5,)])
        result = persist_refresh(cursor, "topaz-1", 5, 9, [("gno.land/r/new", "realm")])
        self.assertEqual(result.status, RefreshStatus.UNCHANGED)
        self.assertEqual(result.current_height, 5)
        self.assertFalse(any(sql.startswith("UPDATE") or sql.startswith("INSERT") for sql, _ in cursor.executed))

    def test_stale_height_is_noop(self):
        cursor = Cursor([(6,)])
        result = persist_refresh(cursor, "topaz-1", 5, 9, [("gno.land/r/new", "realm")])
        self.assertEqual(result.status, RefreshStatus.STALE_IGNORED)
        self.assertEqual(result.current_height, 6)
        self.assertFalse(any(sql.startswith("UPDATE") or sql.startswith("INSERT") for sql, _ in cursor.executed))

    def test_state_upsert_does_not_write_activity_coverage(self):
        cursor = Cursor([None, None, None, (1,)])
        persist_refresh(cursor, "topaz-1", 5, None, [("gno.land/r/demo", "realm")])
        state_sql = next(sql for sql, _ in cursor.executed if sql.startswith("INSERT INTO realm_catalog_state"))
        self.assertNotIn("activity_from_height", state_sql)
        self.assertNotIn("activity_through_height", state_sql)
