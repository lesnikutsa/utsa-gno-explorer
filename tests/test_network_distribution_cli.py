import io, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from scripts import collect_network_distribution as cli

class CliTests(unittest.TestCase):
 def test_rpc_limit_parser(self):
  self.assertEqual(cli.parser().parse_args(['--rpc-limit','3']).rpc_limit,3)
  with self.assertRaises(SystemExit): cli.parser().parse_args(['--rpc-limit','0'])
 def test_safe_runtime_error(self):
  stderr=io.StringIO()
  with patch.object(cli,'run',side_effect=RuntimeError('postgresql://user:secret@host')),redirect_stderr(stderr): self.assertEqual(cli.main([]),1)
  self.assertEqual(stderr.getvalue().strip(),'network distribution failed: internal_error')
 def test_unlock_does_not_mask_original(self):
  class Connection:
   def __enter__(self): return self
   def __exit__(self,*args): return False
  config=unittest.mock.Mock(chain_id='c',database_url='db',rpc_limit=1,rpc_health_max_age=1)
  with patch('psycopg.connect',return_value=Connection()),patch.object(cli.Config,'from_env',return_value=config),patch.object(cli,'acquire_lock',return_value=True),patch.object(cli,'select_sources',side_effect=RuntimeError('original')),patch.object(cli,'release_lock',side_effect=RuntimeError('unlock')):
   with self.assertRaisesRegex(RuntimeError,'original'): cli.run(cli.parser().parse_args([]))
 def test_snapshot_geo_protection_and_normal_save_paths(self):
  class Connection:
   def __enter__(self): return self
   def __exit__(self,*args): return False
  base={'chain_id':'c','rpc_sources_ok':1,'rpc_sources_total':1,'visible_node_ids':2,
        'unique_public_ips':2,'geolocated_public_ips':0}
  config=unittest.mock.Mock(chain_id='c',database_url='db',rpc_limit=1,rpc_health_max_age=1,
                            rpc_timeout=1,snapshot_retention=10)
  scenarios=[(True,dict(base),False,True),(False,dict(base),True,False),
             (True,{**base,'geolocated_public_ips':1},True,False)]
  for has_good,result,should_save,should_skip in scenarios:
   output=io.StringIO()
   with self.subTest(has_good=has_good,geo=result['geolocated_public_ips']), \
        patch('psycopg.connect',return_value=Connection()), \
        patch.object(cli.Config,'from_env',return_value=config), \
        patch.object(cli,'acquire_lock',return_value=True), \
        patch.object(cli,'release_lock'), \
        patch.object(cli,'select_sources',return_value=[{'id':1,'url':'rpc'}]), \
        patch.object(cli,'collect_distribution',return_value=result), \
        patch.object(cli,'has_geolocated_snapshot',return_value=has_good), \
        patch.object(cli,'save_snapshot') as save, redirect_stdout(output):
    self.assertEqual(cli.run(cli.parser().parse_args([])),0)
   self.assertEqual(save.called,should_save)
   self.assertEqual('geo_unavailable' in output.getvalue(),should_skip)
