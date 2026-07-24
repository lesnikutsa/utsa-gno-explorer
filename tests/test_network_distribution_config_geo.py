import os, unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from network_distribution.config import Config
from network_distribution.geo import GeoRecord, lookup_ip, resolve_geo

class ConfigGeoTests(unittest.TestCase):
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
 def test_cache_hits_expiry_and_cap(self):
  now=datetime.now(timezone.utc); valid=GeoRecord('8.8.8.8',True,expires_at=now+timedelta(hours=1)); failed=GeoRecord('1.1.1.1',False,expires_at=now+timedelta(hours=1),error_code='timeout')
  with self.env(NETWORK_DISTRIBUTION_GEO_MAX_LOOKUPS='1'):
   config=Config.from_env()
  with patch('network_distribution.geo.lookup_ip',return_value=GeoRecord('9.9.9.9',False,error_code='timeout',expires_at=now+timedelta(hours=1))) as lookup:
   rows,updates=resolve_geo({'8.8.8.8','1.1.1.1','9.9.9.9','4.4.4.4'},{'8.8.8.8':valid,'1.1.1.1':failed},config)
  self.assertEqual(lookup.call_count,1); self.assertEqual(len(updates),1); self.assertIn('8.8.8.8',rows)
