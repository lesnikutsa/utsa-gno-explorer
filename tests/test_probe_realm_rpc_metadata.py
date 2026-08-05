import json
import os
from pathlib import Path

import pytest

import scripts.probe_realm_rpc_metadata as probe
from indexer.rpc import RpcProbeResult
from scripts.inspect_rpc import RpcError

RAW='RAW_SECRET_SOURCE'

class FakeClient:
    def __init__(self, responses):
        self.responses=responses; self.calls=[]; self.closed=False
    def abci_query(self, path, data, height=None):
        self.calls.append((path,data,height))
        value=self.responses.get((path,data))
        if isinstance(value, Exception): raise value
        if value is None: raise RpcError('missing')
        return value
    def close(self): self.closed=True

def p(url, client, latest=11, selected=False):
    return RpcProbeResult(url=url, healthy=True, selected=selected, chain_id='dev', latest_height=latest, observed_lag=0, catching_up=False, client=client, status_payload={}, response_seconds=0.1)

def responses(path='gno.land/r/demo/users'):
    return {('vm/qfile',path):'main.gno\nmain_test.gno\ngnomod.toml',('vm/qfile',path+'/main.gno'):'package users\nimport "gno.land/p/demo/avl"\n',('vm/qfuncs',path):'[ {"FuncName":"Render","Params":[],"Results":[]} ]',('vm/qdoc',path):json.dumps({'package_path':path,'Funcs':[{}]}),('vm/qpkg_json',path):'{"Name":"users","Doc":"hidden"}',('vm/qrender',path+':'):'<p>hidden</p>',('vm/qstorage',path):'storage: 1, deposit: 2'}

def test_realm_invokes_queries_and_sanitizes():
    c=FakeClient(responses())
    result=probe.probe_path(c,'rpc.example',10,'gno.land/r/demo/users','realm')
    assert [q.query_name for q in result.queries]==['qfile_listing','qfile_source_sample','qfuncs','qdoc','qpkg_json','qrender','qstorage']
    assert ('vm/qrender','gno.land/r/demo/users:',10) in c.calls
    assert RAW not in json.dumps([q.summary for q in result.queries])

def test_package_never_invokes_realm_queries():
    path='gno.land/p/demo/avl'; r=responses(path); r.pop(('vm/qrender',path+':')); r.pop(('vm/qstorage',path))
    c=FakeClient(r)
    result=probe.probe_path(c,'rpc.example',10,path,'package')
    assert ('vm/qrender',path+':',10) not in c.calls
    assert result.queries[-2].status=='not_applicable' and result.queries[-1].status=='not_applicable'

def test_one_query_failure_does_not_stop_others():
    r=responses(); r[('vm/qfuncs','gno.land/r/demo/users')]=RpcError('ABCI query returned an application error')
    c=FakeClient(r); result=probe.probe_path(c,'rpc.example',10,'gno.land/r/demo/users','realm')
    assert any(q.query_name=='qfuncs' and q.status=='application_error' for q in result.queries)
    assert any(q.query_name=='qdoc' and q.status=='ok' for q in result.queries)

def test_safe_host_removes_credentials():
    assert probe.safe_host('https://user:pass@example.com/rpc?token=x')=='example.com'

def test_main_default_first_rpc_all_rpc_latest_minus_one_and_closes(monkeypatch, capsys):
    c1=FakeClient(responses()); c2=FakeClient(responses())
    probes=[p('https://a.example',c1,latest=20), p('https://b.example',c2,latest=30)]
    monkeypatch.setattr(probe,'load_config',lambda: type('C',(),{'rpc_urls':['a','b'],'chain_id':'dev','max_height_lag':10})())
    monkeypatch.setattr(probe,'probe_rpc_endpoints',lambda *a,**k: probes)
    assert probe.main(['--realm-path','gno.land/r/demo/users'])==0
    assert all(call[2]==19 for call in c1.calls) and c2.calls==[]
    assert c1.closed and c2.closed
    assert 'https://' not in capsys.readouterr().out
    c1=FakeClient(responses()); c2=FakeClient(responses()); probes=[p('https://a.example',c1,20), p('https://b.example',c2,30)]
    monkeypatch.setattr(probe,'probe_rpc_endpoints',lambda *a,**k: probes)
    assert probe.main(['--realm-path','gno.land/r/demo/users','--all-suitable-rpcs'])==0
    assert {call[2] for call in c1.calls}=={19} and {call[2] for call in c2.calls}=={29}

def test_json_report_atomic_and_no_raw(tmp_path, monkeypatch):
    out=tmp_path/'report.json'
    report={'schema_version':1,'generated_at':'now','chain_id':'dev','endpoints':[{'summary':'safe'}]}
    probe.write_json_report(out, report)
    assert oct(out.stat().st_mode & 0o777)=='0o600'
    assert json.loads(out.read_text())==report
    link=tmp_path/'link.json'; link.symlink_to(out)
    with pytest.raises(OSError): probe.write_json_report(link, report)

def test_exit_code_2_on_malformed(monkeypatch):
    r=responses(); r[('vm/qfuncs','gno.land/r/demo/users')]='{}'; c=FakeClient(r); probes=[p('https://a.example',c,20)]
    monkeypatch.setattr(probe,'load_config',lambda: type('C',(),{'rpc_urls':['a'],'chain_id':'dev','max_height_lag':10})())
    monkeypatch.setattr(probe,'probe_rpc_endpoints',lambda *a,**k: probes)
    assert probe.main(['--realm-path','gno.land/r/demo/users'])==2

def test_invalid_cli_exits():
    with pytest.raises(SystemExit): probe.main(['--timeout','0','--realm-path','gno.land/r/demo/users'])
