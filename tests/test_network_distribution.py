import unittest
from datetime import datetime, timedelta, timezone
from network_distribution.collector import AllSourcesFailed, collect_distribution
from network_distribution.geo import GeoRecord
from network_distribution.tendermint import PeerIdentity, parse_net_info, parse_peer

class PeerTests(unittest.TestCase):
 def test_addresses_and_filters(self):
  self.assertEqual(parse_peer({'node_info':{'net_address':'ABC@tcp://8.8.8.8:26656'}}), PeerIdentity('abc','8.8.8.8'))
  self.assertEqual(parse_peer({'node_id':'X','remote_addr':'p2p://[2606:4700:4700::1111]:80'}), PeerIdentity('x','2606:4700:4700::1111'))
  for address in ['127.0.0.1:1','10.0.0.1:1','169.254.1.1:1','224.0.0.1:1','0.0.0.0:1','8.8.8.8:99999','example.com:80']:
   self.assertIsNone(parse_peer({'id':'x','ip':address}))
 def test_duplicate_response(self):
  reported, peers=parse_net_info({'result':{'n_peers':'2','peers':[{'id':'A','ip':'8.8.8.8'},{'id':'a','ip':'1.1.1.1'}]}})
  self.assertEqual((reported,len(peers)),(2,1))

class AggregateTests(unittest.TestCase):
 def test_unique_ip_conflict_and_grouping(self):
  responses={1:[PeerIdentity('a','8.8.8.8'),PeerIdentity('b','8.8.8.8')],2:[PeerIdentity('a','1.1.1.1')]}
  def fetch(url, timeout): return len(responses[int(url)]),responses[int(url)]
  geo={'8.8.8.8':GeoRecord('8.8.8.8',True,'North America','US','United States','California',15169,'Google')}
  result=collect_distribution('chain',[{'id':1,'url':'1'},{'id':2,'url':'2'}],geo,fetch=fetch)
  self.assertEqual((result['visible_node_ids'],result['unique_public_ips'],result['node_id_ip_conflicts']),(2,1,1))
  self.assertEqual(result['countries'][0]['count'],1)
 def test_all_fail(self):
  with self.assertRaises(AllSourcesFailed):
   collect_distribution('c',[{'id':1,'url':'x'}],fetch=lambda *_: (_ for _ in ()).throw(ValueError('timeout')))
