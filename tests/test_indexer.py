import copy, json, unittest
from pathlib import Path

from indexer.parsers import parse_height, classify_votes
from indexer.service import IndexerService, plan_range
from indexer.database import FinalizedDataConflict
from scripts.inspect_rpc import RpcError, select_healthy_rpc

FIXTURES=Path(__file__).parent/'fixtures'
def load(n): return json.loads((FIXTURES/n).read_text())
COMMIT_HASH='AQIDBA=='

def payloads(height=122):
    b=load('block.json'); c=load('commit.json'); v=load('validators.json')
    b['result']['block']['header']['height']=str(height); b['result']['block_meta']['block_id']['hash']=COMMIT_HASH
    c['result']['signed_header']['header']['height']=str(height)
    c['result']['signed_header']['commit']['block_id']={'hash':COMMIT_HASH,'parts':{'total':'1'}}
    c['result']['signed_header']['commit']['precommits']=[{'validator_address':'VAL1','signature':'sig1','block_id':{'hash':COMMIT_HASH,'parts':{'total':'1'}}},None,{'validator_address':'VAL3','signature':'sig3','block_id':{'hash':'','parts':{'total':'0'}}}]
    v['result']['block_height']=str(height)
    return b,c,v

class FakeRpc:
    base_url='http://rpc/'
    def __init__(self, by_height): self.by_height=by_height; self.calls=[]
    def get(self, method, **params):
        self.calls.append((method, params)); return self.by_height[params['height']][method]

class FakeDb:
    def __init__(self, fail_height=None): self.rows={}; self.checkpoint=None; self.fail_height=fail_height
    def write_height(self, parsed, chain_id, rpc_url, finalized_tip):
        if self.fail_height==parsed.height: raise RuntimeError('injected db failure')
        existing=self.rows.get(parsed.height)
        if existing and existing.block['hash_base64'] != parsed.block['hash_base64']:
            raise FinalizedDataConflict('conflict')
        self.rows[parsed.height]=parsed; self.checkpoint=parsed.height

class RangeTests(unittest.TestCase):
    def test_bounded_range_validation_and_finalized_tip(self):
        with self.assertRaisesRegex(ValueError,'hard limit'): plan_range(None,1,101,None,200,100,False)
        with self.assertRaisesRegex(ValueError,'above finalized_tip'): plan_range(None,1,11,None,10,100,False)
    def test_empty_database_initialization_requires_start_height(self):
        with self.assertRaisesRegex(ValueError,'start-height'): plan_range(None,None,None,10,20,100,False)
        self.assertEqual(plan_range(None,5,None,2,20,100,False).end_height,6)
    def test_sequential_resume_and_no_skipped_heights(self):
        p=plan_range(10,None,None,3,20,100,False)
        self.assertEqual((p.start_height,p.end_height),(11,13))

class ParserTests(unittest.TestCase):
    def statuses(self, c=None):
        b,base,v=payloads()
        if c is None: c=base
        return {s['signing_address']:s for s in parse_height(122,b,c,v).signatures}
    def test_commit_nil_absent_and_signed_rules(self):
        s=self.statuses()
        self.assertEqual(s['VAL1']['vote_status'],'commit'); self.assertTrue(s['VAL1']['signed'])
        self.assertEqual(s['VAL2']['vote_status'],'absent'); self.assertFalse(s['VAL2']['signed'])
        self.assertEqual(s['VAL3']['vote_status'],'nil'); self.assertFalse(s['VAL3']['signed'])
    def test_invalid_non_matching_vote(self):
        b,c,v=payloads(); c['result']['signed_header']['commit']['precommits'][0]['block_id']['hash']='AgMEBQ=='
        self.assertEqual(parse_height(122,b,c,v).signatures[0]['vote_status'],'invalid')
    def test_duplicate_signer(self):
        b,c,v=payloads(); c['result']['signed_header']['commit']['precommits'].append(copy.deepcopy(c['result']['signed_header']['commit']['precommits'][0]))
        self.assertEqual(self.statuses(c)['VAL1']['vote_status'],'invalid')
    def test_signer_outside_validator_set(self):
        b,c,v=payloads(); c['result']['signed_header']['commit']['precommits'].append({'validator_address':'NOPE','block_id':{'hash':COMMIT_HASH,'parts':{'total':'1'}}})
        with self.assertRaisesRegex(RpcError,'outside active'): parse_height(122,b,c,v)
    def test_malformed_block_id(self):
        b,c,v=payloads(); c['result']['signed_header']['commit']['precommits'][0]['block_id']='bad'
        self.assertEqual(parse_height(122,b,c,v).signatures[0]['vote_status'],'invalid')
    def test_transaction_count_mismatch_and_base64_status(self):
        b,c,v=payloads(); b['result']['block']['data']['txs']=['b2s=','not base64!!!']; b['result']['block']['header']['num_txs']='2'
        txs=parse_height(122,b,c,v).transactions
        self.assertEqual([t['decode_status'] for t in txs], ['decoded','invalid_base64'])
        b['result']['block']['header']['num_txs']='3'
        with self.assertRaisesRegex(RpcError,'transaction count mismatch'): parse_height(122,b,c,v)

class ServiceTests(unittest.TestCase):
    def test_idempotent_reprocessing(self):
        by={122: dict(zip(['block','commit','validators'], payloads(122)))}; db=FakeDb(); svc=IndexerService(FakeRpc(by),db,'test-13','http://rpc',130)
        p=plan_range(None,122,122,None,130,100,False); svc.run(p); svc.run(p)
        self.assertEqual(len(db.rows),1); self.assertEqual(db.checkpoint,122)
    def test_rollback_after_injected_failure_and_checkpoint_unchanged(self):
        by={122: dict(zip(['block','commit','validators'], payloads(122)))}; db=FakeDb(fail_height=122); svc=IndexerService(FakeRpc(by),db,'test-13','http://rpc',130)
        with self.assertRaises(RuntimeError): svc.run(plan_range(None,122,122,None,130,100,False))
        self.assertEqual(db.rows,{}); self.assertIsNone(db.checkpoint)
    def test_conflicting_block_hash(self):
        p=plan_range(None,122,122,None,130,100,False); by={122: dict(zip(['block','commit','validators'], payloads(122)))}; db=FakeDb(); svc=IndexerService(FakeRpc(by),db,'test-13','http://rpc',130); svc.run(p)
        b,c,v=payloads(122); b['result']['block_meta']['block_id']['hash']='AgMEBQ=='; by[122]={'block':b,'commit':c,'validators':v}
        with self.assertRaises(FinalizedDataConflict): svc.run(p)

class RpcHealthTests(unittest.TestCase):
    def test_wrong_chain_catching_up_stale_unavailable(self):
        class C:
            def __init__(self,u,timeout=10): self.base_url=u+'/'
            def get(self,m,**p):
                if 'down' in self.base_url: raise RpcError('down')
                st=load('status.json')
                if 'wrong' in self.base_url: st['result']['node_info']['network']='wrong'
                if 'sync' in self.base_url: st['result']['sync_info']['catching_up']=True
                if 'stale' in self.base_url: st['result']['sync_info']['latest_block_height']='1'
                if 'good' in self.base_url: st['result']['sync_info']['latest_block_height']='20'
                return st
        import unittest.mock as mock
        with mock.patch('scripts.inspect_rpc.GnoRpcClient', C):
            selected,_=select_healthy_rpc(['http://wrong','http://sync','http://down','http://stale','http://good'], expected_chain_id='test-13', max_height_lag=5)
        self.assertEqual(selected.base_url,'http://good/')

if __name__=='__main__': unittest.main()
