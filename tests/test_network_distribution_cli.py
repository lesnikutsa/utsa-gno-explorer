import io, unittest
from contextlib import redirect_stderr
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
