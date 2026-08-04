"""Direct endpoint tests using existing unittest conventions and no HTTP test dependency."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
import api.app as module
from api.config import ApiConfig
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


class RealmNamespaceApiTests(unittest.TestCase):
 def setUp(self): module.app.state.api_config=SimpleNamespace(chain_id='topaz-1')
 def member(self,path='gno.land/r/gnoswap/a',calls=3,success=1,failed=1,unknown=1,
            visible=True,height=8,tx_index=2,timestamp=NOW,first_seen=2,kind='realm'):
  return {'namespace_key':path.split('/')[2] if path.startswith('gno.land/') else 'bad','path':path,
   'path_kind':kind,'rpc_visible':visible,'first_seen_height':first_seen,'last_activity_height':height,
   'last_activity_tx_index':tx_index,'last_activity_at':timestamp,'call_count':calls,
   'successful_call_count':success,'failed_call_count':failed,'unknown_result_call_count':unknown,'member_number':1}
 def item(self,key='gnoswap',members=None):
  members=members or [self.member(path=f'gno.land/r/{key}/a')]
  latest=min((m for m in members if m['call_count']>0),key=lambda m:(-m['last_activity_height'],-m['last_activity_tx_index'],m['path']))
  return {'namespace_key':key,'realm_count':len(members),'called_realm_count':sum(m['call_count']>0 for m in members),
   'rpc_visible_realm_count':sum(bool(m['rpc_visible']) for m in members),'direct_call_count':sum(m['call_count'] for m in members),
   'successful_call_count':sum(m['successful_call_count'] for m in members),'failed_call_count':sum(m['failed_call_count'] for m in members),
   'unknown_result_call_count':sum(m['unknown_result_call_count'] for m in members),
   'first_seen_height':min(m['first_seen_height'] for m in members if m['first_seen_height'] is not None),
   'latest_activity_path':latest['path'],'latest_activity_path_kind':'realm','latest_activity_call_count':latest['call_count'],
   'last_activity_height':latest['last_activity_height'],'last_activity_tx_index':latest['last_activity_tx_index'],
   'last_activity_at':latest['last_activity_at']}
 def result(self,items=None,members=None):
  return {'source':{'chain_id':'topaz-1','indexed_height':9,'observed_height':8,'activity_from_height':1,'activity_through_height':8},
   'items':items or [],'members':members or []}
 def call(self,result,limit=5,scope='all'):
  with patch.object(module.database,'fetch_top_realm_namespaces',return_value=result):
   return module.get_top_realm_namespaces(limit=limit,scope=scope)
 def assert_unavailable(self,result,scope='all'):
  with self.assertRaises(HTTPException) as raised:self.call(result,scope=scope)
  self.assertEqual((raised.exception.status_code,raised.exception.detail),(503,module.UNAVAILABLE_DETAIL))
 def test_defaults_bounds_scope_and_forwarding(self):
  route=next(r for r in module.app.routes if getattr(r,'path',None)=='/api/realm-namespaces/top')
  params={p.name:p for p in route.dependant.query_params}
  self.assertEqual((params['limit'].default,params['scope'].default),(5,'all'))
  self.assertEqual((params['limit'].field_info.metadata[0].ge,params['limit'].field_info.metadata[1].le),(1,10))
  for limit in (1,10):
   with patch.object(module.database,'fetch_top_realm_namespaces',return_value=self.result()) as fetch:
    module.get_top_realm_namespaces(limit=limit,scope='curated')
   self.assertEqual(fetch.call_args.kwargs,{'chain_id':'topaz-1','limit':limit,'curated_only':True,
    'curated_namespace_keys':('gnoswap',)})
 def test_http_parameter_validation_and_curated_forwarding(self):
  outer=self
  class FakeDatabase:
   def __init__(self):self.calls=[]
   def open(self,_config):pass
   def close(self):pass
   def fetch_top_realm_namespaces(self,**kwargs):
    self.calls.append(kwargs); return outer.result()
  fake=FakeDatabase()
  config=ApiConfig(database_url='postgresql://test:password@localhost/test',chain_id='topaz-1')
  with patch.object(module,'database',fake),patch.object(module,'load_config',return_value=config),TestClient(module.app) as client:
   for url in ('/api/realm-namespaces/top','/api/realm-namespaces/top?limit=1',
               '/api/realm-namespaces/top?limit=10','/api/realm-namespaces/top?scope=curated'):
    self.assertEqual(client.get(url).status_code,200,url)
   for url in ('/api/realm-namespaces/top?limit=0','/api/realm-namespaces/top?limit=11',
               '/api/realm-namespaces/top?scope=invalid'):
    self.assertEqual(client.get(url).status_code,422,url)
  self.assertEqual([call['limit'] for call in fake.calls],[5,1,10,5])
  self.assertFalse(fake.calls[0]['curated_only']); self.assertTrue(fake.calls[-1]['curated_only'])
  self.assertEqual(fake.calls[-1]['curated_namespace_keys'],('gnoswap',))
 def test_all_and_curated_metadata_and_rates(self):
  gm=self.member(); gi=self.item(members=[gm]); um=self.member('gno.land/r/unknown/a',calls=2,success=0,failed=0,unknown=2)
  ui=self.item('unknown',[um]); response=self.call(self.result([gi,ui],[gm,um]))
  self.assertEqual(response.items[0].application.display_name,'GnoSwap'); self.assertIsNone(response.items[1].application)
  self.assertEqual(response.items[0].success_rate,.5); self.assertIsNone(response.items[1].success_rate)
  curated=self.call(self.result([gi],[gm]),scope='curated'); self.assertIsNotNone(curated.items[0].application)
  self.assertEqual(self.call(self.result(),scope='curated').items,[])
 def test_namespace_ranking_and_aggregate_fail_closed(self):
  member=self.member(); base=self.item(members=[member])
  cases=[]
  for change in ({'namespace_key':'bad/path'},{'direct_call_count':0},{'rpc_visible_realm_count':0},
                 {'realm_count':0},{'called_realm_count':2},{'rpc_visible_realm_count':2},
                 {'successful_call_count':99},{'direct_call_count':True},{'direct_call_count':-1}):
   cases.append([base|change])
  cases.extend([[base,base],[self.item('z',[self.member('gno.land/r/z/a')]),base]])
  for items in cases:
   members=[member] if len(items)==1 and items[0].get('namespace_key')=='gnoswap' else []
   with self.subTest(items=items):self.assert_unavailable(self.result(items,members))
 def test_member_and_cross_checks_fail_closed(self):
  good=self.member(); base=self.item(members=[good])
  variants=[]
  wrong=self.member('gno.land/r/other/a'); variants.append([wrong])
  package=good|{'path_kind':'package'}; variants.append([package])
  variants.append([good,good])
  variants.append([self.member('gno.land/r/gnoswap/b'),good])
  variants.append([good|{'last_activity_tx_index':None}])
  variants.append([good|{'last_activity_height':0}])
  variants.append([good|{'last_activity_at':'bad'}])
  variants.append([good|{'last_activity_height':None,'last_activity_tx_index':None,'last_activity_at':None}])
  variants.append([self.member(calls=0,success=0,failed=0,unknown=0)])
  variants.append([good|{'successful_call_count':2}])
  for members in variants:
   with self.subTest(members=members):self.assert_unavailable(self.result([base],members))
  mismatch=base|{'first_seen_height':3}; self.assert_unavailable(self.result([mismatch],[good]))
  mismatch=base|{'latest_activity_path':'gno.land/r/gnoswap/other'}; self.assert_unavailable(self.result([mismatch],[good]))
  mismatch=base|{'latest_activity_call_count':good['call_count']+1}; self.assert_unavailable(self.result([mismatch],[good]))
  many=[self.member(f'gno.land/r/gnoswap/{i:03}',calls=0,success=0,failed=0,unknown=0,
        height=None,tx_index=None,timestamp=None) for i in range(101)]
  self.assert_unavailable(self.result([base],many))
 def test_valid_truncated_members_return_first_hundred(self):
  members=[self.member(f'gno.land/r/gnoswap/{index:03}',calls=0,success=0,failed=0,unknown=0,
            height=None,tx_index=None,timestamp=None,first_seen=index+2) for index in range(100)]
  item={'namespace_key':'gnoswap','realm_count':101,'called_realm_count':1,'rpc_visible_realm_count':101,
   'direct_call_count':7,'successful_call_count':5,'failed_call_count':1,'unknown_result_call_count':1,
   'first_seen_height':1,'latest_activity_path':'gno.land/r/gnoswap/100','latest_activity_path_kind':'realm',
   'latest_activity_call_count':7,'last_activity_height':50,'last_activity_tx_index':4,'last_activity_at':NOW}
  response=self.call(self.result([item],members))
  self.assertTrue(response.items[0].realms_truncated)
  self.assertEqual(len(response.items[0].realms),100)
  self.assertEqual([realm.path for realm in response.items[0].realms],
                   [f'gno.land/r/gnoswap/{index:03}' for index in range(100)])
  self.assertNotIn(item['latest_activity_path'],[realm.path for realm in response.items[0].realms])
 def test_activity_and_public_errors(self):
  good=self.member(); base=self.item(members=[good])
  for change in ({'last_activity_tx_index':None},{'last_activity_height':0},{'last_activity_at':'bad'},
                 {'latest_activity_call_count':0},{'latest_activity_path_kind':'package'}):
   self.assert_unavailable(self.result([base|change],[good]))
  with patch.object(module.database,'fetch_top_realm_namespaces',return_value=None):
   with self.assertRaises(HTTPException) as raised:module.get_top_realm_namespaces(limit=5,scope='all')
  self.assertEqual((raised.exception.status_code,raised.exception.detail),(404,'Realm catalog not found'))
  with patch.object(module.database,'fetch_top_realm_namespaces',side_effect=RuntimeError('secret')):
   with self.assertRaises(HTTPException) as raised:module.get_top_realm_namespaces(limit=5,scope='all')
  self.assertEqual(raised.exception.detail,module.UNAVAILABLE_DETAIL); self.assertNotIn('secret',raised.exception.detail)
