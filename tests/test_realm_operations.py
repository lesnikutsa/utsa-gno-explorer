"""Focused non-PostgreSQL contracts for Realm operator commands."""
import unittest
from scripts.rebuild_realm_activity import RebuildError, rebuild_cursor
from scripts.refresh_realm_catalog import persist_refresh

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

class RefreshPersistenceTests(unittest.TestCase):
    def test_invalid_set_is_rejected_before_visibility_update(self):
        cursor=Cursor([])
        with self.assertRaises(ValueError): persist_refresh(cursor,"topaz-1",5,None,[("bad","realm")])
        self.assertEqual(cursor.executed,[])
    def test_duplicate_set_is_rejected_before_visibility_update(self):
        cursor=Cursor([]); paths=[('gno.land/r/x','realm')]*2
        with self.assertRaises(ValueError): persist_refresh(cursor,"topaz-1",5,None,paths)
        self.assertEqual(cursor.executed,[])
