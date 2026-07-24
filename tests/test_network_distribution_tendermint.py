import unittest
from unittest.mock import Mock, patch
from network_distribution.tendermint import PeerIdentity, fetch_net_info, parse_net_info, parse_peer

class TendermintPeerTests(unittest.TestCase):
 def test_common_net_address_forms(self):
  forms=['node@8.8.8.8:26656','node@tcp://8.8.8.8:26656','tcp://node@8.8.8.8:26656','p2p://node@8.8.8.8:26656']
  for value in forms:
   with self.subTest(value=value): self.assertEqual(parse_peer({'node_info':{'net_address':value}}),PeerIdentity('node','8.8.8.8'))
 def test_net_address_without_embedded_id_and_fallbacks(self):
  self.assertEqual(parse_peer({'node_info':{'id':'NODE','net_address':'tcp://8.8.8.8:26656'}}),PeerIdentity('node','8.8.8.8'))
  self.assertEqual(parse_peer({'node_id':'NODE','node_info':{'net_address':'8.8.8.8:26656'}}),PeerIdentity('node','8.8.8.8'))
  self.assertEqual(parse_peer({'id':'NODE','remote_ip':'8.8.8.8'}),PeerIdentity('node','8.8.8.8'))
 def test_ipv6_and_invalid_ids(self):
  self.assertEqual(parse_peer({'id':'NODE','remote_addr':'[2606:4700:4700:0:0:0:0:1111]:1'}),PeerIdentity('node','2606:4700:4700::1111'))
  for node in ['', '   ', 'has space', 'bad\nvalue', 'x'*256]: self.assertIsNone(parse_peer({'id':node,'ip':'8.8.8.8'}))
 def test_bare_ipv6_forms(self):
  forms=['2606:4700:4700::1111','tcp://2606:4700:4700::1111','p2p://2606:4700:4700::1111']
  for value in forms:
   with self.subTest(value=value): self.assertEqual(parse_peer({'id':'NODE','remote_ip':value}),PeerIdentity('node','2606:4700:4700::1111'))
  self.assertEqual(parse_peer({'node_info':{'net_address':'node@2001:4860:4860:0:0:0:0:8888'}}),PeerIdentity('node','2001:4860:4860::8888'))
  for value in ['fc00::1','::1','fe80::1','2606:4700:::1111']:
   with self.subTest(value=value): self.assertIsNone(parse_peer({'id':'node','ip':value}))
 def test_rejected_addresses(self):
  values=['bad','example.com:80','8.8.8.8:0','8.8.8.8:65536','10.0.0.1','127.0.0.1','169.254.1.1','224.0.0.1','192.0.2.1','0.0.0.0','fc00::1','::1']
  for value in values:
   with self.subTest(value=value): self.assertIsNone(parse_peer({'id':'node','ip':value}))
 def test_duplicate_id_within_response(self):
  _, peers=parse_net_info({'result':{'peers':[{'id':'NODE','ip':'8.8.8.8'},{'id':'node','ip':'1.1.1.1'}]}})
  self.assertEqual(peers,[PeerIdentity('node','8.8.8.8')])
 def test_safe_path_join_and_only_net_info(self):
  response=Mock(); response.raise_for_status.return_value=None; response.json.return_value={'result':{'peers':[]}}
  with patch('network_distribution.tendermint.requests.get',return_value=response) as get:
   fetch_net_info('https://rpc.example/base/?token=secret',10)
  self.assertEqual(get.call_args.args[0],'https://rpc.example/base/net_info')
