import unittest
from network_distribution.collector import AllSourcesFailed, collect_distribution
from network_distribution.geo import GeoRecord
from network_distribution.tendermint import PeerIdentity

class CollectorTests(unittest.TestCase):
 def test_dedup_conflict_country_code_and_asn(self):
  replies={'one':[PeerIdentity('a','8.8.8.8'),PeerIdentity('b','8.8.8.8'),PeerIdentity('c','9.9.9.9')], 'two':[PeerIdentity('a','1.1.1.1')]}
  geo={'8.8.8.8':GeoRecord('8.8.8.8',True,'North America','US','United States','X',1,'Zulu'), '9.9.9.9':GeoRecord('9.9.9.9',True,'North America','US','USA','Y',1,'Alpha')}
  result=collect_distribution('c',[{'id':1,'url':'one'},{'id':2,'url':'two'}],geo,fetch=lambda u,t:(len(replies[u]),replies[u]))
  self.assertEqual((result['visible_node_ids'],result['unique_public_ips'],result['node_id_ip_conflicts']),(3,2,1))
  self.assertEqual(result['countries'],[{'code':'US','name':'United States','count':2}])
  self.assertEqual(result['providers'],[{'asn':1,'name':'Alpha','count':2}])
 def test_partial_and_all_failure(self):
  def fetch(url,_):
   if url=='bad': raise ValueError('timeout')
   return 0,[]
  result=collect_distribution('c',[{'id':1,'url':'bad'},{'id':2,'url':'ok'}],fetch=fetch)
  self.assertEqual(result['rpc_sources_ok'],1); self.assertEqual(result['sources'][0]['error_code'],'timeout')
  with self.assertRaises(AllSourcesFailed): collect_distribution('c',[{'id':1,'url':'bad'}],fetch=fetch)
 def test_no_unknown_rows(self):
  result=collect_distribution('c',[{'id':1,'url':'ok'}],fetch=lambda *_:(1,[PeerIdentity('a','8.8.8.8')]))
  self.assertEqual((result['regions'],result['countries'],result['providers']),([],[],[]))
