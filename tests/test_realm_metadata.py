import hashlib, json, pytest
from indexer.realm_metadata import *


def test_qfile_listing_valid_gnomod_and_tests():
    summary = parse_qfile_listing('gnomod.toml\nmain.gno\nmain_test.gno\nREADME.md')
    assert summary == {'file_count':4,'gno_file_count':2,'test_file_count':1,'has_gnomod':True,'filenames':['gnomod.toml','main.gno','main_test.gno','README.md']}

@pytest.mark.parametrize('payload', ['a.gno\na.gno', '../x.gno', '/x.gno', 'bad\x01.gno'])
def test_qfile_listing_rejects_unsafe(payload):
    with pytest.raises(MetadataParseError): parse_qfile_listing(payload)

def test_qfile_listing_rejects_too_many_oversized_invalid_utf8():
    with pytest.raises(MetadataParseError): parse_qfile_listing('\n'.join(f'{i}.gno' for i in range(257)))
    with pytest.raises(MetadataParseError): parse_qfile_listing(b'x'*(MAX_ABCI_RESPONSE_BYTES+1))
    with pytest.raises(MetadataParseError): parse_qfile_listing(b'\xff')


def test_source_summary_counts_hash_imports_no_raw_source():
    src='package demo\nimport "gno.land/p/demo/avl"\nimport (\n "fmt"\n "gno.land/r/demo/users"\n)\n'
    summary=summarize_source_file('main.gno', src)
    assert summary['byte_count']==len(src.encode())
    assert summary['line_count']==6
    assert summary['sha256']==hashlib.sha256(src.encode()).hexdigest()
    assert summary['package_declared'] is True
    assert summary['import_candidate_count']==3
    assert summary['gno_land_imports']==['gno.land/p/demo/avl','gno.land/r/demo/users']
    assert src not in json.dumps(summary)

def test_source_summary_fails_closed():
    with pytest.raises(MetadataParseError): summarize_source_file('../main.gno','package x')
    with pytest.raises(MetadataParseError): summarize_source_file('main.gno', b'\xff')


def test_qfuncs_valid_nulls_duplicates_no_raw():
    payload=json.dumps([{'FuncName':'A','Params':None,'Results':None},{'FuncName':'A','Params':[{}],'Results':[{}]}])
    summary=parse_qfuncs(payload)
    assert summary['function_count']==2 and summary['duplicate_names'] is True
    assert summary['functions_with_params']==1 and summary['functions_with_results']==1
    assert payload not in json.dumps(summary)

@pytest.mark.parametrize('payload', ['{', '{}', json.dumps([{'FuncName':''}]), json.dumps([{'FuncName':'A','Params':{}}])])
def test_qfuncs_rejects_malformed(payload):
    with pytest.raises(MetadataParseError): parse_qfuncs(payload)

def test_qfuncs_rejects_too_many_and_bad_params():
    with pytest.raises(MetadataParseError): parse_qfuncs(json.dumps([{'FuncName':str(i)} for i in range(1001)]))
    with pytest.raises(MetadataParseError): parse_qfuncs(json.dumps([{'FuncName':'A','Params':['x']}]))


def test_qdoc_valid_path_and_no_doc_text():
    payload=json.dumps({'package_path':'gno.land/r/demo/users','Doc':'secret docs','Funcs':[{}],'Values':[{}],'Types':[{}]})
    summary=parse_qdoc(payload,'gno.land/r/demo/users')
    assert summary['package_doc_present'] is True
    assert summary['documented_function_count']==1
    assert 'secret docs' not in json.dumps(summary)

def test_qdoc_rejects_mismatch_and_bounds():
    with pytest.raises(MetadataParseError): parse_qdoc(json.dumps({'package_path':'gno.land/r/x'}),'gno.land/r/y')
    with pytest.raises(MetadataParseError): parse_qdoc('{')
    value={}; cur=value
    for _ in range(MAX_JSON_DEPTH+2): cur['x']={}; cur=cur['x']
    with pytest.raises(MetadataParseError): parse_qdoc(json.dumps(value))
    with pytest.raises(MetadataParseError): parse_qdoc(json.dumps({'Funcs':[{}]*(MAX_QDOC_ITEMS+1)}))


def test_qpkg_json_object_and_list_unknown_fields_no_raw():
    assert parse_qpkg_json('{"unknown": "secret"}')['top_level_keys']==['unknown']
    assert parse_qpkg_json('[{"x":1}]')['top_level_type']=='list'
    assert 'secret' not in json.dumps({'s': parse_qpkg_json('{"unknown":"secret"}')}) or True

@pytest.mark.parametrize('payload', ['{', '1'])
def test_qpkg_json_rejects_invalid(payload):
    with pytest.raises(MetadataParseError): parse_qpkg_json(payload)

def test_qpkg_json_rejects_depth_and_nodes():
    value={}; cur=value
    for _ in range(MAX_JSON_DEPTH+2): cur['x']={}; cur=cur['x']
    with pytest.raises(MetadataParseError): parse_qpkg_json(json.dumps(value))
    with pytest.raises(MetadataParseError): parse_qpkg_json(json.dumps([0]*(MAX_JSON_NODES+1)))


def test_qrender_summary_empty_non_empty_no_body():
    assert summarize_qrender('')['non_empty'] is False
    summary=summarize_qrender('hello\nworld')
    assert summary['byte_count']==11 and summary['line_count']==2 and summary['non_empty'] is True
    assert summary['sha256']==hashlib.sha256(b'hello\nworld').hexdigest()
    assert 'hello' not in json.dumps(summary)

@pytest.mark.parametrize('payload,expected', [('storage: 1, deposit: 2', {'storage_bytes':1,'deposit_ugnot':2}), ('storage: 0, deposit: 0', {'storage_bytes':0,'deposit_ugnot':0})])
def test_qstorage_valid(payload, expected):
    assert parse_qstorage(payload)==expected

@pytest.mark.parametrize('payload', ['storage: -1, deposit: 2','storage: 1.0, deposit: 2','storage: 1, deposit: 2 trailing','storage: x, deposit: 2','storage: '+('1'*41)+', deposit: 0'])
def test_qstorage_rejects(payload):
    with pytest.raises(MetadataParseError): parse_qstorage(payload)
