import copy
import unittest
from indexer.realm_catalog import aggregate_block, extract_observations, parse_qpaths, path_kind
from indexer.transaction_summary import MAX_SUMMARY_BYTES, normalize_summary, summary_size_bytes
from scripts import init_database

def summary(messages,status='parsed'):
 return {'parse_status':status,'messages':messages}
class RealmCatalogTests(unittest.TestCase):
 def test_paths(self):
  self.assertEqual(path_kind('gno.land/r/demo'),'realm'); self.assertEqual(path_kind('gno.land/p/demo'),'package')
  for value in ('gno.land/e/x','std/foo','gno.land/r/a b','gno.land/r/a?x','gno.land/r/a#x',
                'gno.land/r/','gno.land/r/x/','gno.land/r/x//y'):
   self.assertIsNone(path_kind(value))
  maximum='gno.land/r/'+('x'*(256-len('gno.land/r/')))
  self.assertEqual(len(maximum),256); self.assertEqual(path_kind(maximum),'realm')
  self.assertIsNone(path_kind(maximum+'x'))
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
 def test_qpaths_unique_limit(self):
  payload='\n'.join(f'gno.land/r/x{i}' for i in range(10001))
  with self.assertRaisesRegex(ValueError,'too_many'): parse_qpaths(payload)
 def test_package_path_completeness_rules(self):
  prefix='gno.land/r/'
  path160=prefix+('a'*(160-len(prefix)))
  path256=prefix+('b'*(256-len(prefix)))
  def observed(path,marker='missing'):
   message={'type':'gno.vm.MsgCall','package_path':path}
   if marker != 'missing': message['package_path_complete']=marker
   return extract_observations(summary([message]))
  self.assertEqual(len(observed(prefix+'short')),1)
  self.assertEqual(len(observed(path160,True)),1)
  self.assertEqual(len(observed(path256,True)),1)
  self.assertEqual(observed(path160),())
  self.assertEqual(observed(prefix+'short',False),())
  self.assertEqual(observed(path256+'x',False),())
 def test_distinct_long_paths_do_not_merge(self):
  shared='gno.land/r/'+('a'*160)
  first=shared+'x'; second=shared+'y'
  aggregates=aggregate_block([(0,summary([
   {'type':'gno.vm.MsgCall','package_path':first,'package_path_complete':True},
   {'type':'gno.vm.MsgCall','package_path':second,'package_path_complete':True},
  ]),'success')])
  self.assertEqual({item.path for item in aggregates},{first,second})
 def test_normalization_preserves_path_limit_only(self):
  prefix='gno.land/r/'; path=prefix+('x'*(256-len(prefix)))
  candidate={'schema_version':1,'chain_family':'gno','parse_status':'parsed','message_count':1,
   'messages_truncated':False,'primary':{'type':'x','category':'x','action':'x','label':'x'},
   'messages':[{'type':'gno.vm.MsgCall','package_path':path,'package_path_complete':True,
                'function':'f'*200}]}
  normalized=normalize_summary(candidate)
  self.assertEqual(normalized['messages'][0]['package_path'],path)
  self.assertIs(normalized['messages'][0]['package_path_complete'],True)
  self.assertEqual(len(normalized['messages'][0]['function']),160)
  self.assertLessEqual(summary_size_bytes(normalized),MAX_SUMMARY_BYTES)
 def test_qpaths_retains_256_character_path(self):
  path='gno.land/r/'+('q'*(256-len('gno.land/r/')))
  self.assertEqual(parse_qpaths(path),((path,'realm'),))
 def test_postgres_path_kind_canonical_form_remains_exact(self):
  expectations=init_database.FINAL_SCHEMA_EXPECTATIONS
  snapshot=copy.deepcopy({
   'tables':expectations['tables'],'columns':expectations['columns'],
   'primary_keys':expectations['primary_keys'],'unique_constraints':expectations['unique_constraints'],
   'foreign_keys':expectations['foreign_keys'],'check_constraints':expectations['check_constraints'],
   'indexes':expectations['indexes'],
  })
  snapshot['check_constraints']['realm_catalog_path_kind_check']="CHECK (path_kind IN ('realm', 'package'))"
  init_database.validate_schema_snapshot(snapshot)
  snapshot['check_constraints']['realm_catalog_path_kind_check']="CHECK (path_kind IN ('realm', 'package', 'ephemeral'))"
  with self.assertRaises(init_database.SchemaCompatibilityError):
   init_database.validate_schema_snapshot(snapshot)
  snapshot['check_constraints'].pop('realm_catalog_path_kind_check')
  with self.assertRaises(init_database.SchemaCompatibilityError):
   init_database.validate_schema_snapshot(snapshot)
 def test_postgres_path_canonical_form_remains_exact(self):
  expectations=init_database.FINAL_SCHEMA_EXPECTATIONS
  snapshot=copy.deepcopy({
   'tables':expectations['tables'],'columns':expectations['columns'],
   'primary_keys':expectations['primary_keys'],'unique_constraints':expectations['unique_constraints'],
   'foreign_keys':expectations['foreign_keys'],'check_constraints':expectations['check_constraints'],
   'indexes':expectations['indexes'],
  })
  canonical=("CHECK (((char_length(path) >= 1) AND (char_length(path) <= 256) "
   "AND (path ~ '^gno\\.land/[rp]/[!-\\.0-~]+(/[!-\\.0-~]+)*$'::text) "
   "AND (path !~ '[?#]'::text) AND (((path_kind = 'realm'::text) "
   "AND (path ~~ 'gno.land/r/%'::text)) OR ((path_kind = 'package'::text) "
   "AND (path ~~ 'gno.land/p/%'::text)))))")
  snapshot['check_constraints']['realm_catalog_path_check']=canonical
  init_database.validate_schema_snapshot(snapshot)
  incompatible=(
   canonical.replace("+(/[!-\\.0-~]+)*$", "+(/[!-\\.0-~]+)*/?$") ,
   canonical.replace("(/[!-\\.0-~]+)*$", "(/[!-\\.0-~]*)*$"),
   canonical.replace("[rp]/", "[rpe]/"),
  )
  for changed in incompatible:
   snapshot['check_constraints']['realm_catalog_path_check']=changed
   with self.assertRaises(init_database.SchemaCompatibilityError):
    init_database.validate_schema_snapshot(snapshot)
  snapshot['check_constraints']['realm_catalog_path_check']=canonical
  snapshot['check_constraints'].pop('realm_catalog_path_check')
  with self.assertRaises(init_database.SchemaCompatibilityError):
   init_database.validate_schema_snapshot(snapshot)
if __name__=='__main__': unittest.main()
