import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from indexer.realm_metadata import MAX_FILES, MAX_JSON_DEPTH, MAX_SOURCE_LINES
from indexer.realm_metadata_persistence import (
    JsonCapability,
    MetadataFile,
    MetadataPersistenceError,
    MetadataRefreshState,
    MetadataSnapshot,
    RenderCapability,
    StaleMetadataSnapshot,
    StorageCapability,
    metadata_fingerprint,
    persist_metadata_refresh_state_cursor,
    prepare_metadata_snapshot,
    publish_metadata_snapshot,
    publish_metadata_snapshot_cursor,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def realm(**changes):
    files = (
        MetadataFile(
            "main.gno",
            'package demo\nimport "gno.land/p/demo/lib"\nimport x "gno.land/p/demo/lib"\n',
        ),
        MetadataFile("main_test.gno", "package demo\n"),
        MetadataFile("gnomod.toml", "module = 'demo'\n"),
    )
    value = MetadataSnapshot(
        "dev", "gno.land/r/demo", "realm", 10, "complete",
        tuple(item.filename for item in files), files, NOW,
    )
    return replace(value, **changes)


def test_valid_realm_snapshot_derives_files_imports_and_counts():
    result = prepare_metadata_snapshot(realm())
    assert (result.gno_file_count, result.test_file_count, result.has_gnomod) == (2, 1, True)
    assert result.dependency_count == 1
    assert [item.file_kind for item in result.files] == ["gno_source", "gno_test", "gnomod"]
    assert result.files[0].imports == (("gno.land/p/demo/lib", "package"),)
    assert result.total_file_lines == 5


def test_qfile_listing_must_be_exact_and_nonempty():
    with pytest.raises(MetadataPersistenceError, match="empty_listing"):
        prepare_metadata_snapshot(realm(expected_filenames=(), files=()))
    with pytest.raises(MetadataPersistenceError, match="missing_listed_file"):
        prepare_metadata_snapshot(realm(files=realm().files[:-1]))
    extra = (*realm().files, MetadataFile("extra.txt", "x"))
    with pytest.raises(MetadataPersistenceError, match="extra_fetched_file"):
        prepare_metadata_snapshot(realm(files=extra))
    with pytest.raises(MetadataPersistenceError, match="invalid_listing"):
        prepare_metadata_snapshot(realm(expected_filenames=("main.gno", "main.gno")))
    assert prepare_metadata_snapshot(realm()).files


def test_listing_and_fingerprint_are_order_independent():
    snapshot = realm(
        expected_filenames=tuple(reversed(realm().expected_filenames)),
        files=tuple(reversed(realm().files)),
    )
    assert prepare_metadata_snapshot(snapshot).content_sha256 == prepare_metadata_snapshot(realm()).content_sha256
    assert metadata_fingerprint(snapshot.files) == metadata_fingerprint(realm().files)


def test_valid_package_requires_realm_capabilities_not_applicable():
    value = realm(path="gno.land/p/demo", path_kind="package")
    assert prepare_metadata_snapshot(value).snapshot.path_kind == "package"
    with pytest.raises(MetadataPersistenceError, match="package_realm_capability"):
        prepare_metadata_snapshot(replace(value, qrender=RenderCapability("rpc_error")))


@pytest.mark.parametrize("changes", [
    {"path_kind": "package"}, {"chain_id": ""}, {"observed_height": 0},
    {"observed_height": True}, {"collected_at": datetime(2026, 1, 1)},
    {"source_rpc_endpoint_id": True},
    {"expected_filenames": ("../main.gno",), "files": (MetadataFile("../main.gno", "x"),)},
])
def test_invalid_snapshot_inputs_are_rejected(changes):
    with pytest.raises(MetadataPersistenceError):
        prepare_metadata_snapshot(realm(**changes))


def test_file_count_size_aggregate_and_line_bounds():
    files = tuple(MetadataFile(f"{index}.txt", "") for index in range(MAX_FILES + 1))
    with pytest.raises(MetadataPersistenceError, match="invalid_listing"):
        prepare_metadata_snapshot(realm(expected_filenames=tuple(x.filename for x in files), files=files))
    large = (MetadataFile("x.txt", "x" * (1024 * 1024 + 1)),)
    with pytest.raises(MetadataPersistenceError, match="file_too_large"):
        prepare_metadata_snapshot(realm(expected_filenames=("x.txt",), files=large))
    aggregate = tuple(MetadataFile(f"{index}.txt", "x" * (1024 * 1024)) for index in range(9))
    with pytest.raises(MetadataPersistenceError, match="snapshot_too_large"):
        prepare_metadata_snapshot(realm(expected_filenames=tuple(x.filename for x in aggregate), files=aggregate))
    lines = (MetadataFile("x.txt", "\n" * (MAX_SOURCE_LINES + 1)),)
    with pytest.raises(MetadataPersistenceError, match="too_many_lines"):
        prepare_metadata_snapshot(realm(expected_filenames=("x.txt",), files=lines))


def test_real_parsers_derive_json_summaries_and_reject_generic_json():
    path = realm().path
    qdoc = JsonCapability("ok", json.dumps({"package_path": path, "funcs": [], "values": [], "types": []}))
    qpkg = JsonCapability("ok", '[{"name":"demo"}]')
    qfuncs = JsonCapability("ok", '[{"FuncName":"Hello","Params":[],"Results":[]}]')
    prepared = prepare_metadata_snapshot(realm(qdoc=qdoc, qpkg_json=qpkg, qfuncs=qfuncs))
    assert prepared.qdoc.summary["value_count"] == 0
    assert prepared.qpkg_json.summary["top_level_type"] == "list"
    assert prepared.qfuncs.summary["function_count"] == 1
    with pytest.raises(MetadataPersistenceError, match="invalid_qdoc"):
        prepare_metadata_snapshot(realm(qdoc=JsonCapability("ok", '{"package_path":"gno.land/r/other"}')))
    with pytest.raises(MetadataPersistenceError, match="invalid_qfuncs"):
        prepare_metadata_snapshot(realm(qfuncs=JsonCapability("ok", '{"bounded":true}')))
    with pytest.raises(MetadataPersistenceError, match="invalid_qfuncs"):
        prepare_metadata_snapshot(realm(qfuncs=JsonCapability("ok", '[{"FuncName":"X","Params":{}}]')))


def test_render_storage_and_integer_bounds():
    render = RenderCapability("ok", "a" * 64, 12, 2, True)
    storage = StorageCapability("ok", 10**39, 2)
    assert prepare_metadata_snapshot(realm(qrender=render, qstorage=storage)).snapshot.qrender == render
    assert "body" not in RenderCapability.__dataclass_fields__
    for bad in (
        RenderCapability("ok", "a" * 64, 1048577, 1, True),
        RenderCapability("ok", "a" * 64, 0, 1, True),
        RenderCapability("ok", "a" * 64, True, 1, True),
    ):
        with pytest.raises(MetadataPersistenceError, match="invalid_qrender"):
            prepare_metadata_snapshot(realm(qrender=bad))
    with pytest.raises(MetadataPersistenceError, match="invalid_qstorage"):
        prepare_metadata_snapshot(realm(qstorage=StorageCapability("ok", True, 2)))


class MemoryCursor:
    """Small stateful SQL double exercising the publication SQL decisions."""
    def __init__(self, state, fail_on=None):
        self.state = state
        self.fail_on = fail_on
        self.calls = []
        self._row = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("injected write failure")
        if normalized.startswith("SELECT observed_height"):
            parent = self.state.get("parent")
            if parent is None:
                self._row = None
            else:
                keys = (
                    "observed_height", "collected_at", "content_sha256",
                    "qdoc_summary", "qdoc_payload", "qdoc_last_successful_height",
                    "qpkg_json_summary", "qpkg_json_payload", "qpkg_json_last_successful_height",
                    "qfuncs_summary", "qfuncs_payload", "qfuncs_last_successful_height",
                    "qrender_sha256", "qrender_byte_count", "qrender_line_count",
                    "qrender_non_empty", "qrender_last_successful_height",
                    "qstorage_bytes", "qstorage_deposit_ugnot", "qstorage_last_successful_height",
                )
                json_keys = {
                    "qdoc_summary", "qdoc_payload", "qpkg_json_summary",
                    "qpkg_json_payload", "qfuncs_summary", "qfuncs_payload",
                }
                self._row = tuple(
                    json.loads(parent[key])
                    if key in json_keys and parent.get(key) is not None
                    else parent.get(key)
                    for key in keys
                )
        elif normalized.startswith("INSERT INTO realm_metadata ("):
            names = (
                "chain_id", "path", "path_kind", "observed_height", "collection_status",
                "content_sha256", "file_count", "gno_file_count", "test_file_count", "has_gnomod",
                "total_file_bytes", "total_file_lines", "dependency_count", "source_rpc_endpoint_id",
                "qdoc_status", "qdoc_summary", "qdoc_payload", "qdoc_last_successful_height",
                "qpkg_json_status", "qpkg_json_summary", "qpkg_json_payload", "qpkg_json_last_successful_height",
                "qfuncs_status", "qfuncs_summary", "qfuncs_payload", "qfuncs_last_successful_height",
                "qrender_status", "qrender_sha256", "qrender_byte_count", "qrender_line_count",
                "qrender_non_empty", "qrender_last_successful_height", "qstorage_status",
                "qstorage_bytes", "qstorage_deposit_ugnot", "qstorage_last_successful_height", "collected_at",
            )
            self.state["parent"] = dict(zip(names, params))
        elif normalized.startswith("DELETE FROM realm_metadata_files"):
            self.state["files"] = {}
            self.state["imports"] = set()
        elif normalized.startswith("INSERT INTO realm_metadata_files"):
            self.state.setdefault("files", {})[params[2]] = params
        elif normalized.startswith("INSERT INTO realm_metadata_imports"):
            self.state.setdefault("imports", set()).add(params[2:])

    def fetchone(self):
        return self._row


class Transaction:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): self.before = copy.deepcopy(self.connection.state)
    def __exit__(self, exc_type, *_):
        if exc_type: self.connection.state.clear(); self.connection.state.update(self.before)
        return False


class MemoryConnection:
    def __init__(self, fail_on=None): self.state = {}; self.fail_on = fail_on; self.closed = False; self.cursors = []
    def transaction(self): return Transaction(self)
    def cursor(self):
        cursor = MemoryCursor(self.state, self.fail_on); self.cursors.append(cursor); return ContextCursor(cursor)


class ContextCursor:
    def __init__(self, cursor): self.cursor = cursor
    def __enter__(self): return self.cursor
    def __exit__(self, *_): return False


def test_actual_publication_first_changed_unchanged_and_stale():
    connection = MemoryConnection()
    first = publish_metadata_snapshot(connection, realm())
    assert not connection.closed
    assert connection.state["parent"]["file_count"] == len(connection.state["files"]) == 3
    assert connection.state["parent"]["dependency_count"] == 1
    assert ("main.gno", "gno.land/p/demo/lib", "package") in connection.state["imports"]

    newer = realm(observed_height=11, collected_at=NOW + timedelta(minutes=1))
    publish_metadata_snapshot(connection, newer)
    unchanged_calls = connection.cursors[-1].calls
    assert not any(sql.startswith("DELETE FROM") for sql, _ in unchanged_calls)
    assert connection.state["parent"]["observed_height"] == 11

    changed_files = (MetadataFile("main.gno", "package changed\n"),)
    changed = realm(
        observed_height=12, collected_at=NOW + timedelta(minutes=2),
        expected_filenames=("main.gno",), files=changed_files,
    )
    publish_metadata_snapshot(connection, changed)
    assert set(connection.state["files"]) == {"main.gno"}
    before = copy.deepcopy(connection.state)
    with pytest.raises(StaleMetadataSnapshot, match="stale_metadata_snapshot"):
        publish_metadata_snapshot(connection, realm(observed_height=11, collected_at=NOW + timedelta(minutes=3)))
    assert connection.state == before


def test_actual_publication_preserves_all_optional_success_values_on_failure():
    connection = MemoryConnection()
    success = realm(
        qdoc=JsonCapability("ok", json.dumps({"package_path": realm().path, "funcs": [], "values": [], "types": []})),
        qpkg_json=JsonCapability("ok", '{"name":"demo"}'),
        qfuncs=JsonCapability("ok", '[{"FuncName":"Hello","Params":[],"Results":[]}]'),
        qrender=RenderCapability("ok", "a" * 64, 5, 1, True),
        qstorage=StorageCapability("ok", 7, 8),
    )
    publish_metadata_snapshot(connection, success)
    saved = copy.deepcopy(connection.state["parent"])
    failure = replace(
        realm(observed_height=11, collected_at=NOW + timedelta(minutes=1)),
        qdoc=JsonCapability("rpc_error"), qpkg_json=JsonCapability("application_error"),
        qfuncs=JsonCapability("invalid_response"), qrender=RenderCapability("rpc_error"),
        qstorage=StorageCapability("application_error"),
    )
    publish_metadata_snapshot(connection, failure)
    parent = connection.state["parent"]
    for prefix in ("qdoc", "qpkg_json", "qfuncs"):
        assert parent[f"{prefix}_payload"] == saved[f"{prefix}_payload"]
        assert parent[f"{prefix}_summary"] == saved[f"{prefix}_summary"]
        assert parent[f"{prefix}_last_successful_height"] == 10
    assert parent["qrender_sha256"] == saved["qrender_sha256"]
    assert parent["qstorage_bytes"] == saved["qstorage_bytes"]
    assert parent["qdoc_status"] == "rpc_error"


def test_failed_child_write_rolls_back_previous_parent_and_children():
    connection = MemoryConnection()
    publish_metadata_snapshot(connection, realm())
    before = copy.deepcopy(connection.state)
    connection.fail_on = "INSERT INTO realm_metadata_files"
    changed = realm(
        observed_height=11, collected_at=NOW + timedelta(minutes=1),
        expected_filenames=("new.txt",), files=(MetadataFile("new.txt", "new"),),
    )
    with pytest.raises(RuntimeError, match="injected"):
        publish_metadata_snapshot(connection, changed)
    assert connection.state == before
    assert not connection.closed


def test_completeness_failure_occurs_before_sql():
    cursor = MemoryCursor({})
    with pytest.raises(MetadataPersistenceError, match="missing_listed_file"):
        publish_metadata_snapshot_cursor(cursor, realm(files=realm().files[:-1]))
    assert cursor.calls == []


class RefreshCursor:
    def __init__(self): self.calls = []
    def execute(self, sql, params): self.calls.append((sql, params))
    def fetchone(self): return None


def test_refresh_state_validation_and_monotonic_upsert():
    cursor = RefreshCursor()
    state = MetadataRefreshState("dev", 10, "running", 2, 0, 0, NOW)
    persist_metadata_refresh_state_cursor(cursor, state)
    assert "FOR UPDATE" in cursor.calls[0][0]
    assert "ON CONFLICT" in cursor.calls[1][0]
    invalid = (
        replace(state, observed_height=True),
        replace(state, selected_path_count=True),
        replace(state, started_at=datetime(2026, 1, 1)),
        replace(state, run_status="complete"),
        replace(state, run_status="complete", completed_at=NOW - timedelta(seconds=1)),
    )
    for value in invalid:
        with pytest.raises(MetadataPersistenceError):
            persist_metadata_refresh_state_cursor(cursor, value)
