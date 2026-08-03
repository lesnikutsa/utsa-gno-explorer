"""Focused contracts for the continuous Realm catalog upsert."""
import inspect
import unittest
from indexer import database
from indexer.realm_catalog import aggregate_block

class Cursor:
 def __init__(self): self.calls=[]
 def execute(self,sql,params=()): self.calls.append((sql,params))
def summary(messages): return {'parse_status':'parsed','messages':messages}
class RealmIndexerTests(unittest.TestCase):
 def test_multiple_calls_are_one_upsert_with_status_counters(self):
  messages=[{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]*3
  aggregate=aggregate_block([(2,summary(messages),'failed')])
  cursor=Cursor(); database.upsert_transaction_catalog_aggregates(cursor,'topaz-1',8,'time',aggregate)
  self.assertEqual(len(cursor.calls),1)
  params=cursor.calls[0][1]
  self.assertEqual((params[10],params[11],params[12],params[13]),(3,0,3,0))
 def test_missing_execution_result_is_unknown(self):
  aggregate=aggregate_block([(0,summary([{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]),None)])[0]
  self.assertEqual((aggregate.call_count,aggregate.unknown_result_call_count),(1,1))
 def test_sql_enforces_height_idempotency_and_preserves_rpc_fields(self):
  aggregate=aggregate_block([(0,summary([{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]),'success')])
  cursor=Cursor(); database.upsert_transaction_catalog_aggregates(cursor,'topaz-1',8,'time',aggregate)
  sql=cursor.calls[0][0]
  self.assertIn('EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0)',sql)
  self.assertNotIn('seen_via_rpc=',sql); self.assertNotIn('rpc_visible=',sql); self.assertNotIn('last_rpc_seen_at=',sql)
 def test_deploy_and_activity_positions_are_aggregated(self):
  add={'type':'gno.vm.MsgAddPackage','package_path':'gno.land/r/x'}; call={'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}
  aggregate=aggregate_block([(4,summary([add,call]),'success'),(7,summary([call]),'success')])[0]
  self.assertEqual((aggregate.deploy_tx_index,aggregate.last_activity_tx_index),(4,7))
 def test_catalog_is_not_consensus_conflict_input(self):
  source=inspect.getsource(database._verify_finalized_conflicts)
  self.assertNotIn('realm',source.lower())
