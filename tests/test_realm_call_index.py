from indexer.database import RealmCallCoverageError, advance_realm_call_coverage

class Cursor:
 def __init__(self,row): self.row=row; self.queries=[]; self.rowcount=0
 def execute(self,sql,params): self.queries.append((sql,params)); self.rowcount=1
 def fetchone(self): return self.row

def test_absent_coverage_is_not_claimed():
 cursor=Cursor(None); result=advance_realm_call_coverage(cursor,'dev',10)
 assert not result.advanced and len(cursor.queries)==1

def test_exact_next_and_replay_coverage():
 cursor=Cursor((1,9)); assert advance_realm_call_coverage(cursor,'dev',10).advanced
 cursor=Cursor((1,10)); assert not advance_realm_call_coverage(cursor,'dev',10).advanced

def test_coverage_gap_fails_closed():
 import pytest
 with pytest.raises(RealmCallCoverageError): advance_realm_call_coverage(Cursor((1,8)),'dev',10)

def test_schema_contains_exact_pagination_and_exclusions():
 sql=open('database/migrations/0009_add_realm_call_index.sql').read()
 assert '(chain_id, path, block_height DESC, tx_index DESC, message_index DESC)' in sql
 for excluded in ('raw_result','error_text','gas_used','tx_hash_hex'):
  assert excluded not in sql
