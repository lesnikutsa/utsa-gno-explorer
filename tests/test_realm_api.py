"""Direct endpoint tests using existing unittest conventions and no HTTP test dependency."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import api.app as module
from api.database import ApiDatabase, REALM_CATALOG_ITEMS_SQL, REALM_CATALOG_SUMMARY_SQL, REALM_TOP_ITEMS_SQL

NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def result(rows=None):
 return {'summary':{'total_items':2,'total_realms':1,'total_packages':1,'rpc_visible_items':1,'active_24h':1,'indexed_height':9,'observed_height':10,'refreshed_at':NOW,'activity_from_height':1,'activity_through_height':9},'items':rows or []}
def row(path='gno.land/r/x',height=8,success=1,failed=0,unknown=1):
 return {'path':path,'path_kind':'realm','rpc_visible':True,'deployer_address':None,'deploy_height':None,'deploy_tx_index':None,'first_seen_height':None,'last_activity_height':height,'last_activity_tx_index':0 if height is not None else None,'last_activity_at':NOW if height is not None else None,'call_count':success+failed+unknown,'successful_call_count':success,'failed_call_count':failed,'unknown_result_call_count':unknown}
class RealmApiTests(unittest.TestCase):
 def setUp(self): module.app.state.api_config=SimpleNamespace(chain_id='topaz-1')
 def call(self,**kw):
  defaults=dict(limit=25,kind='all',q=None,before_activity_height=None,before_path=None); defaults.update(kw); return module.get_realms(**defaults)
 def test_missing_is_exact_404(self):
  with patch.object(module.database,'fetch_realm_catalog',return_value=None):
   with self.assertRaises(HTTPException) as raised:self.call()
  self.assertEqual((raised.exception.status_code,raised.exception.detail),(404,'Realm catalog not found'))
 def test_cursor_validation(self):
  with self.assertRaises(HTTPException): self.call(before_activity_height=1)
  with self.assertRaises(HTTPException): self.call(before_activity_height=1,before_path='bad')
 def test_chain_and_literal_query_are_forwarded(self):
  with patch.object(module.database,'fetch_realm_catalog',return_value=result()) as fetch:self.call(q=r'%_\\')
  self.assertEqual(fetch.call_args.kwargs['chain_id'],'topaz-1'); self.assertEqual(fetch.call_args.kwargs['q'],r'%_\\')
  self.assertIn('WHERE s.chain_id=%s',REALM_CATALOG_SUMMARY_SQL)
  self.assertIn('%s::text IS NULL',REALM_CATALOG_ITEMS_SQL)
  self.assertIn('strpos(lower(path), lower(%s::text)) > 0',REALM_CATALOG_ITEMS_SQL)
  self.assertIn('%s::bigint IS NULL',REALM_CATALOG_ITEMS_SQL)
  self.assertIn('COALESCE(last_activity_height,-1) < %s::bigint',REALM_CATALOG_ITEMS_SQL)
  self.assertIn('COALESCE(last_activity_height,-1) = %s::bigint AND path > %s::text',REALM_CATALOG_ITEMS_SQL)
  self.assertNotIn(' LIKE ',REALM_CATALOG_ITEMS_SQL)
 def test_success_rate_excludes_unknown_and_null_when_undecided(self):
  with patch.object(module.database,'fetch_realm_catalog',return_value=result([row(),row('gno.land/r/y',None,0,0,2)])):
   response=self.call()
  self.assertEqual(response.items[0].success_rate,1.0); self.assertIsNone(response.items[1].success_rate)
 def test_null_activity_next_cursor_is_minus_one(self):
  rows=[row('gno.land/r/a',None,0,0,0),row('gno.land/r/b',None,0,0,0)]
  with patch.object(module.database,'fetch_realm_catalog',return_value=result(rows)):
   response=self.call(limit=1)
  self.assertEqual(response.pagination.next_before_activity_height,-1)
 def test_malformed_stored_data_fails_closed(self):
  with patch.object(module.database,'fetch_realm_catalog',return_value=result([row('gno.land/r/bad/')])):
   with self.assertRaises(HTTPException) as raised:self.call()
  self.assertEqual(raised.exception.status_code,503)

 def test_top_sql_has_exact_filters_order_and_limit(self):
  normalized=' '.join(REALM_TOP_ITEMS_SQL.split())
  self.assertIn("WHERE chain_id = %s AND path_kind = 'realm' AND rpc_visible = true AND call_count > 0",normalized)
  self.assertIn('ORDER BY call_count DESC, COALESCE(last_activity_height, -1) DESC, path COLLATE "C" ASC LIMIT %s',normalized)

 def test_top_database_sets_stable_read_only_snapshot_before_queries(self):
  statements=[]
  class Cursor:
   def __enter__(self): return self
   def __exit__(self,*_args): return False
   def execute(self,sql,params=None): statements.append((sql,params))
   def fetchone(self): return result()['summary'] | {'chain_id':'topaz-1'}
   def fetchall(self): return []
  class Context:
   def __init__(self,value): self.value=value
   def __enter__(self): return self.value
   def __exit__(self,*_args): return False
  class Connection:
   def transaction(self): return Context(None)
   def cursor(self): return Cursor()
  database=ApiDatabase(); database.pool=SimpleNamespace(connection=lambda **_kwargs:Context(Connection()))
  response=database.fetch_top_realms(chain_id='topaz-1',limit=5)
  self.assertEqual(response['items'],[])
  self.assertEqual(statements[0],('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY',None))
  self.assertEqual(statements[1],(REALM_CATALOG_SUMMARY_SQL,('topaz-1',)))
  self.assertEqual(statements[2],(REALM_TOP_ITEMS_SQL,('topaz-1',5)))

 def top_result(self,rows=None):
  source=result()['summary']; source['chain_id']='topaz-1'
  return {'source':source,'items':rows or []}

 def test_top_source_success_rate_and_default_limit(self):
  with patch.object(module.database,'fetch_top_realms',return_value=self.top_result([row()])) as fetch:
   response=module.get_top_realms(limit=5)
  self.assertEqual(fetch.call_args.kwargs,{'chain_id':'topaz-1','limit':5})
  self.assertEqual(response.source.activity_from_height,1)
  self.assertEqual(response.items[0].success_rate,1.0)
  parameter=next(route for route in module.app.routes if getattr(route,'path',None)=='/api/realms/top').dependant.query_params[0]
  self.assertEqual((parameter.default,parameter.field_info.metadata[0].ge,parameter.field_info.metadata[1].le),(5,1,10))

 def test_top_missing_and_database_failure_are_public(self):
  with patch.object(module.database,'fetch_top_realms',return_value=None):
   with self.assertRaises(HTTPException) as missing:module.get_top_realms(limit=5)
  self.assertEqual((missing.exception.status_code,missing.exception.detail),(404,'Realm catalog not found'))
  with patch.object(module.database,'fetch_top_realms',side_effect=RuntimeError('secret')):
   with self.assertRaises(HTTPException) as failed:module.get_top_realms(limit=5)
  self.assertEqual((failed.exception.status_code,failed.exception.detail),(503,module.UNAVAILABLE_DETAIL))
  self.assertNotIn('secret',failed.exception.detail)

 def test_top_rejects_nonqualifying_duplicates_order_and_bad_counters(self):
  invalid=[]
  package=row('gno.land/p/pkg'); package['path_kind']='package'; invalid.append([package])
  historical=row(); historical['rpc_visible']=False; invalid.append([historical])
  invalid.append([row(success=0,failed=0,unknown=0)])
  invalid.append([row(),row()])
  invalid.append([row('gno.land/r/a',success=2),row('gno.land/r/b',success=3)])
  malformed=row(); malformed['call_count']=99; invalid.append([malformed])
  for rows in invalid:
   with self.subTest(rows=rows), patch.object(module.database,'fetch_top_realms',return_value=self.top_result(rows)):
    with self.assertRaises(HTTPException) as raised:module.get_top_realms(limit=5)
   self.assertEqual(raised.exception.status_code,503)

 def test_top_ties_follow_height_then_path(self):
  rows=[row('gno.land/r/a',9),row('gno.land/r/b',8),row('gno.land/r/c',8)]
  with patch.object(module.database,'fetch_top_realms',return_value=self.top_result(rows)):
   self.assertEqual([item.path for item in module.get_top_realms(limit=5).items],[entry['path'] for entry in rows])

 def test_top_rejects_increasing_activity_height_with_equal_calls(self):
  rows=[row('gno.land/r/a',8),row('gno.land/r/b',9)]
  with patch.object(module.database,'fetch_top_realms',return_value=self.top_result(rows)):
   with self.assertRaises(HTTPException) as raised:module.get_top_realms(limit=5)
  self.assertEqual(raised.exception.status_code,503)

 def test_top_rejects_descending_path_with_equal_calls_and_height(self):
  rows=[row('gno.land/r/b',8),row('gno.land/r/a',8)]
  with patch.object(module.database,'fetch_top_realms',return_value=self.top_result(rows)):
   with self.assertRaises(HTTPException) as raised:module.get_top_realms(limit=5)
  self.assertEqual(raised.exception.status_code,503)
