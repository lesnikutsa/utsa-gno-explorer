from dataclasses import replace
from datetime import datetime, timezone

import pytest

from indexer.realm_metadata import MAX_FILES, MAX_JSON_DEPTH, MAX_STRING_LENGTH
from indexer.realm_metadata_persistence import (
    JsonCapability, MetadataFile, MetadataPersistenceError, MetadataRefreshState,
    MetadataSnapshot, RenderCapability, StorageCapability, metadata_fingerprint,
    persist_metadata_refresh_state_cursor, prepare_metadata_snapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def realm(**changes):
    value = MetadataSnapshot("dev", "gno.land/r/demo", "realm", 10, "complete", (
        MetadataFile("main.gno", 'package demo\nimport "gno.land/p/demo/lib"\nimport x "gno.land/p/demo/lib"\n'),
        MetadataFile("main_test.gno", "package demo\n"), MetadataFile("gnomod.toml", "module = 'demo'\n"),
    ), NOW)
    return replace(value, **changes)


def test_valid_realm_snapshot_derives_files_imports_and_counts():
    result = prepare_metadata_snapshot(realm())
    assert (result.gno_file_count, result.test_file_count, result.has_gnomod) == (2, 1, True)
    assert result.dependency_count == 1
    assert result.files[0].file_kind == "gno_source"
    assert result.files[1].file_kind == "gno_test"
    assert result.files[2].file_kind == "gnomod"
    assert result.files[0].imports == (("gno.land/p/demo/lib", "package"),)
    assert result.files[0].byte_count == len(result.files[0].content.encode())
    assert result.total_file_lines == 5


def test_valid_package_requires_realm_capabilities_not_applicable():
    value = realm(path="gno.land/p/demo", path_kind="package")
    assert prepare_metadata_snapshot(value).snapshot.path_kind == "package"
    with pytest.raises(MetadataPersistenceError, match="package_realm_capability"):
        prepare_metadata_snapshot(replace(value, qrender=RenderCapability("rpc_error")))


@pytest.mark.parametrize("changes", [
    {"path_kind":"package"}, {"chain_id":""}, {"observed_height":0},
    {"files":(MetadataFile("../main.gno", "package p"),)},
    {"files":(MetadataFile("a.gno", "package p"), MetadataFile("a.gno", "package p"))},
])
def test_invalid_snapshot_inputs_are_rejected(changes):
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(**changes))


def test_file_count_and_size_bounds():
    files=tuple(MetadataFile(f"{i}.txt", "") for i in range(MAX_FILES+1))
    with pytest.raises(MetadataPersistenceError, match="too_many_files"): prepare_metadata_snapshot(realm(files=files))
    with pytest.raises(MetadataPersistenceError, match="file_too_large"): prepare_metadata_snapshot(realm(files=(MetadataFile("x.txt", "x"*(1024*1024+1)),)))
    files=tuple(MetadataFile(f"{i}.txt", "x"*(1024*1024)) for i in range(9))
    with pytest.raises(MetadataPersistenceError, match="snapshot_too_large"): prepare_metadata_snapshot(realm(files=files))


def test_fingerprint_is_order_independent_and_content_sensitive():
    files=(MetadataFile("b", "two"),MetadataFile("a", "one"))
    assert metadata_fingerprint(files) == metadata_fingerprint(reversed(files))
    assert metadata_fingerprint(files) != metadata_fingerprint((MetadataFile("b", "changed"),files[1]))


def test_noncanonical_gno_land_imports_are_ignored():
    value=realm(files=(MetadataFile("main.gno", 'package p\nimport "gno.land/x/nope"\nimport "example.com/x"'),))
    assert prepare_metadata_snapshot(value).files[0].imports == ()


def test_bounded_json_success_and_failures():
    good=JsonCapability("ok", {"count":1}, {"items":[]})
    assert prepare_metadata_snapshot(realm(qdoc=good)).snapshot.qdoc == good
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(qdoc=JsonCapability("ok", {}, {"x":"x"*(MAX_STRING_LENGTH+1)})))
    deep={}; cursor=deep
    for _ in range(MAX_JSON_DEPTH+1): cursor["x"]={}; cursor=cursor["x"]
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(qpkg_json=JsonCapability("ok", {}, deep)))
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(qfuncs=JsonCapability("rpc_error", {}, [])))


def test_render_and_storage_summaries_are_bounded_without_body_field():
    render=RenderCapability("ok", "a"*64, 12, 2, True)
    storage=StorageCapability("ok", 10**39, 2)
    assert prepare_metadata_snapshot(realm(qrender=render,qstorage=storage)).snapshot.qrender == render
    assert "body" not in RenderCapability.__dataclass_fields__
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(qrender=RenderCapability("ok", "BAD", 1, 1, True)))
    with pytest.raises(MetadataPersistenceError): prepare_metadata_snapshot(realm(qstorage=StorageCapability("ok", -1, 2)))


class Cursor:
    def __init__(self): self.calls=[]
    def execute(self, sql, params): self.calls.append((sql,params))


def test_refresh_state_validation_and_upsert():
    cursor=Cursor(); state=MetadataRefreshState("dev",10,"running",2,0,0,NOW)
    persist_metadata_refresh_state_cursor(cursor,state)
    assert len(cursor.calls)==1
    with pytest.raises(MetadataPersistenceError):
        persist_metadata_refresh_state_cursor(cursor,replace(state,published_path_count=2,failed_path_count=1))
    with pytest.raises(MetadataPersistenceError):
        persist_metadata_refresh_state_cursor(cursor,replace(state,run_status="complete"))
