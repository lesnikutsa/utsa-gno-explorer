import os, unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from network_distribution.config import Config
from network_distribution.geo import GeoRecord, lookup_ip, normalize_external_text, resolve_geo

class ConfigGeoTests(unittest.TestCase):
 def test_external_text_normalization(self):
  self.assertEqual(normalize_external_text("  North\t America\n ",128),"North America")
  self.assertIsNone(normalize_external_text(" \x00\t ",128))
  self.assertIsNone(normalize_external_text(123,128))
  self.assertIsNone(normalize_external_text(b"bytes",128))
  self.assertEqual(normalize_external_text("x"*300,128),"x"*128)
 def env(self, **values):
  return patch.dict(os.environ, {'DATABASE_URL':'postgresql://db','GNO_CHAIN_ID':'chain',**values}, clear=True)
 def test_independent_timeouts_and_ranges(self):
  with self.env(NETWORK_DISTRIBUTION_RPC_TIMEOUT='11',NETWORK_DISTRIBUTION_GEO_TIMEOUT='12'):
   config=Config.from_env(); self.assertEqual((config.rpc_timeout,config.geo_timeout),(11,12))
  for value in ['0','121']:
   with self.env(NETWORK_DISTRIBUTION_RPC_TIMEOUT=value), self.assertRaises(ValueError): Config.from_env()
 def test_provider_priorities(self):
  def record(connection):
   response=Mock(); response.raise_for_status.return_value=None; response.json.return_value={'success':True,'country_code':'US','connection':connection}; return response
  for connection,name in [({'asn':1,'org':'Org','isp':'ISP'},'Org'),({'asn':1,'isp':'ISP'},'ISP'),({'asn':1},'AS1')]:
   with patch('network_distribution.geo.requests.get',return_value=record(connection)): self.assertEqual(lookup_ip('8.8.8.8','https://geo',1,3600,60).provider_name,name)
 def test_success_fields_are_bounded_and_failure_is_empty(self):
  response=Mock(); response.raise_for_status.return_value=None
  response.json.return_value={'success':True,'continent':' C  '*100,'country_code':' us ','country':'N'*200,'region':'R'*300,'connection':{'asn':1,'org':' O\t '*200}}
  with patch('network_distribution.geo.requests.get',return_value=response): row=lookup_ip('8.8.8.8','https://private.example/token',1,3600,60)
  self.assertLessEqual(len(row.continent_name),128); self.assertLessEqual(len(row.country_name),128); self.assertLessEqual(len(row.region_name),255); self.assertLessEqual(len(row.provider_name),255)
  self.assertEqual(row.lookup_provider,'ipwho.is'); self.assertIsNone(row.country_code); self.assertIsNone(row.error_code)
  failed_response=Mock(); failed_response.raise_for_status.return_value=None; failed_response.json.return_value={'success':False,'continent':'secret','connection':{'org':'secret'}}
  with patch('network_distribution.geo.requests.get',return_value=failed_response): failed=lookup_ip('8.8.8.8','https://geo',1,3600,60)
  self.assertEqual((failed.lookup_success,failed.continent_name,failed.country_code,failed.country_name,failed.region_name,failed.asn,failed.provider_name),(False,None,None,None,None,None,None))
  self.assertEqual(failed.error_code,'lookup_failed')
 def test_cache_hits_expiry_and_cap(self):
  now=datetime.now(timezone.utc); valid=GeoRecord('8.8.8.8',True,expires_at=now+timedelta(hours=1)); failed=GeoRecord('1.1.1.1',False,expires_at=now+timedelta(hours=1),error_code='timeout')
  with self.env(NETWORK_DISTRIBUTION_GEO_MAX_LOOKUPS='1'):
   config=Config.from_env()
  with patch('network_distribution.geo.lookup_ip',return_value=GeoRecord('9.9.9.9',False,error_code='timeout',expires_at=now+timedelta(hours=1))) as lookup:
   rows,updates=resolve_geo({'8.8.8.8','1.1.1.1','9.9.9.9','4.4.4.4'},{'8.8.8.8':valid,'1.1.1.1':failed},config)
  self.assertEqual(lookup.call_count,1); self.assertEqual(len(updates),1); self.assertIn('8.8.8.8',rows)
 def test_http_outcomes(self):
  rate_limited=Mock(status_code=429)
  server_error=Mock(status_code=500)
  server_error.raise_for_status.side_effect=__import__('requests').HTTPError('internal body')
  valid=Mock(status_code=200); valid.raise_for_status.return_value=None
  valid.json.return_value={'success':True,'country_code':'US','country':'United States','continent':'North America','connection':{'asn':64500,'org':'Provider'}}
  cases=[(rate_limited,'rate_limited'),(server_error,'request_error')]
  for response,error_code in cases:
   with self.subTest(error_code=error_code),patch('network_distribution.geo.requests.get',return_value=response):
    row=lookup_ip('8.8.8.8','https://geo',1,3600,60)
    self.assertFalse(row.lookup_success); self.assertEqual(row.error_code,error_code)
    self.assertGreater(row.expires_at,row.fetched_at)
  with patch('network_distribution.geo.requests.get',side_effect=__import__('requests').Timeout):
   self.assertEqual(lookup_ip('8.8.8.8','https://geo',1,3600,60).error_code,'timeout')
  with patch('network_distribution.geo.requests.get',return_value=valid):
   self.assertTrue(lookup_ip('8.8.8.8','https://geo',1,3600,60).lookup_success)
