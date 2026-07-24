import copy
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts import init_database, migrate_network_distribution_schema

class Cursor:
 def __init__(self,present,snapshots): self.present=set(present); self.snapshots=iter(snapshots); self.ddl=0
 def __enter__(self): return self
 def __exit__(self,*args): return False
 def execute(self,sql,args=None):
  if sql.lstrip().startswith('-- Aggregated'): self.ddl+=1
 def fetchall(self): return [(name,) for name in self.present]
class Connection:
 def __init__(self,cursor): self.value=cursor; self.commits=0; self.rolled_back=False
 def __enter__(self): return self
 def __exit__(self,kind,*args): self.rolled_back=kind is not None; return False
 def cursor(self): return self.value
 def commit(self): self.commits+=1

def snap(expectations):
 return {'tables':set(expectations['tables']),'columns':copy.deepcopy(expectations['columns']),'primary_keys':copy.deepcopy(expectations['primary_keys']),'unique_constraints':set(expectations['unique_constraints']),'foreign_keys':set(expectations['foreign_keys']),'check_constraints':copy.deepcopy(expectations['check_constraints']),'indexes':copy.deepcopy(expectations['indexes'])}

def run(present,snapshots):
 cursor=Cursor(present,snapshots); connection=Connection(cursor)
 with patch.object(migrate_network_distribution_schema,'fetch_schema_snapshot',side_effect=snapshots):
  result=migrate_network_distribution_schema.migrate('safe',connect=lambda _:connection)
 return result,connection,cursor

def test_actual_network_migration_applies_and_reruns_without_ddl():
 pre=snap(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS); final=snap(init_database.FINAL_SCHEMA_EXPECTATIONS)
 result,connection,cursor=run(set(),[pre,final]); assert (result,connection.commits,cursor.ddl)==('applied',1,1)
 result,connection,cursor=run(migrate_network_distribution_schema.TABLES,[final]); assert (result,connection.commits,cursor.ddl)==('already-compatible',1,0)

def test_actual_network_migration_rejects_partial_empty_and_invalid_before_ddl():
 final=snap(init_database.FINAL_SCHEMA_EXPECTATIONS)
 for present,snapshots in [({'network_distribution_geo_cache'},[]),(set(),[{'tables':set()}]),(set(),[{**snap(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS),'indexes':{}}])]:
  cursor=Cursor(present,snapshots); connection=Connection(cursor)
  with patch.object(migrate_network_distribution_schema,'fetch_schema_snapshot',side_effect=snapshots),pytest.raises(Exception): migrate_network_distribution_schema.migrate('safe',connect=lambda _:connection)
  assert connection.commits==0 and connection.rolled_back and cursor.ddl==0
