import unittest
from indexer.realm_catalog import aggregate_block, extract_observations, parse_qpaths, path_kind

def summary(messages,status='parsed'):
 return {'parse_status':status,'messages':messages}
class RealmCatalogTests(unittest.TestCase):
 def test_paths(self):
  self.assertEqual(path_kind('gno.land/r/demo'),'realm'); self.assertEqual(path_kind('gno.land/p/demo'),'package')
  for value in ('gno.land/e/x','std/foo','gno.land/r/a b','gno.land/r/a?x','gno.land/r/a#x','gno.land/r/'):
   self.assertIsNone(path_kind(value))
 def test_extraction_is_bounded(self):
  messages=[{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]*21
  self.assertEqual(len(extract_observations(summary(messages))),20)
  self.assertEqual(extract_observations(summary(messages,'invalid')),())
 def test_add_and_call(self):
  values=extract_observations(summary([{'type':'gno.vm.MsgAddPackage','package_path':'gno.land/p/x'}, {'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]))
  self.assertEqual([v.observation_type for v in values],['deployment','call'])
 def test_aggregate(self):
  aggregate=aggregate_block([(0,summary([{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]),'success'),(1,summary([{'type':'gno.vm.MsgCall','package_path':'gno.land/r/x'}]),None)])[0]
  self.assertEqual((aggregate.call_count,aggregate.successful_call_count,aggregate.unknown_result_call_count,aggregate.last_activity_tx_index),(2,1,1,1))
 def test_qpaths(self):
  self.assertEqual(parse_qpaths('gno.land/r/x\ngno.land/p/y\ngno.land/r/x\n'),(('gno.land/p/y','package'),('gno.land/r/x','realm')))
  for value in ('','gno.land/e/x','gno.land/r/x\nbad'):
   with self.assertRaises(ValueError): parse_qpaths(value)
if __name__=='__main__': unittest.main()
