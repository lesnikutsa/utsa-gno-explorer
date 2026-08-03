"""Direct endpoint tests using existing unittest conventions and no HTTP test dependency."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import api.app as module
from api.database import REALM_CATALOG_ITEMS_SQL, REALM_CATALOG_SUMMARY_SQL

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
