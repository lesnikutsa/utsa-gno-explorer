from __future__ import annotations

from datetime import datetime, timezone

from indexer.realm_metadata_collector import CollectionRequest, collect_path_metadata
from scripts.inspect_rpc import RpcError
from scripts.refresh_realm_metadata import select_catalog_paths


REALM = "gno.land/r/demo"
PACKAGE = "gno.land/p/lib"
QDOC = '{"package_path":"gno.land/r/demo","funcs":[],"values":[],"types":[]}'
QFUNCS = '[{"FuncName":"Render","Params":[],"Results":[]}]'


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def abci_query(self, path, data, height):
        self.calls.append((path, data, height))
        value = self.responses[(path, data)]
        if isinstance(value, Exception):
            raise value
        return value


def realm_responses(path=REALM):
    return {
        ("vm/qfile", path): "main.gno\nweb/assets.txt",
        ("vm/qfile", f"{path}/main.gno"): "package demo\n",
        ("vm/qfile", f"{path}/web/assets.txt"): "asset",
        ("vm/qdoc", path): QDOC.replace(REALM, path),
        ("vm/qpkg_json", path): '{}',
        ("vm/qfuncs", path): QFUNCS,
        ("vm/qrender", f"{path}:"): "secret render body\n",
        ("vm/qstorage", path): "storage: 12, deposit: 34",
    }


def collect(client, path=REALM, kind="realm"):
    return collect_path_metadata(
        client, CollectionRequest("dev", path, kind, 123, 7),
        collected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_exact_height_listing_and_every_nested_file_are_collected():
    client = FakeClient(realm_responses())
    result = collect(client)
    assert result.status == "complete"
    assert result.snapshot.expected_filenames == ("main.gno", "web/assets.txt")
    assert [item.filename for item in result.snapshot.files] == ["main.gno", "web/assets.txt"]
    assert all(call[2] == 123 for call in client.calls)
    assert client.calls[:3] == [
        ("vm/qfile", REALM, 123),
        ("vm/qfile", f"{REALM}/main.gno", 123),
        ("vm/qfile", f"{REALM}/web/assets.txt", 123),
    ]


def test_required_listing_or_listed_file_failure_is_not_publishable():
    listing = FakeClient({("vm/qfile", REALM): RpcError("private transport detail")})
    assert collect(listing).snapshot is None
    responses = realm_responses()
    responses[("vm/qfile", f"{REALM}/web/assets.txt")] = RpcError("private detail")
    result = collect(FakeClient(responses))
    assert result.status == "failed"
    assert result.failure_code == "qfile_file"
    assert "private" not in repr(result)


def test_complete_realm_capabilities_and_render_body_discarded():
    result = collect(FakeClient(realm_responses()))
    snapshot = result.snapshot
    assert snapshot.qdoc.status == snapshot.qpkg_json.status == snapshot.qfuncs.status == "ok"
    assert snapshot.qrender.status == "ok"
    assert snapshot.qrender.byte_count == len("secret render body\n")
    assert snapshot.qstorage.storage_bytes == 12
    assert "secret render body" not in repr(snapshot)


def test_optional_status_mapping_makes_realm_partial():
    responses = realm_responses()
    responses[("vm/qdoc", REALM)] = "not json"
    responses[("vm/qpkg_json", REALM)] = RpcError("transport includes a secret")
    responses[("vm/qfuncs", REALM)] = RpcError("ABCI query returned an application error")
    result = collect(FakeClient(responses))
    assert result.status == "partial"
    assert result.snapshot.qdoc.status == "invalid_response"
    assert result.snapshot.qpkg_json.status == "rpc_error"
    assert result.snapshot.qfuncs.status == "application_error"
    assert "secret" not in repr(result)


def test_package_realm_capabilities_are_not_applicable_and_error_is_partial():
    responses = realm_responses(PACKAGE)
    responses[("vm/qfuncs", PACKAGE)] = RpcError("ABCI query returned an application error")
    client = FakeClient(responses)
    result = collect(client, PACKAGE, "package")
    assert result.status == "partial"
    assert result.snapshot.qrender.status == "not_applicable"
    assert result.snapshot.qstorage.status == "not_applicable"
    assert not any(call[0] in {"vm/qrender", "vm/qstorage"} for call in client.calls)


class CatalogCursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, params):
        self.query = query

    def fetchone(self):
        return (99,)

    def fetchall(self):
        return [(PACKAGE, "package"), (REALM, "realm")]


def test_catalog_selection_deduplicates_filters_orders_and_limits():
    cursor = CatalogCursor()
    selection = select_catalog_paths(cursor, "dev", [REALM, REALM], 1)
    assert selection.observed_height == 99
    assert selection.paths == ((REALM, "realm"),)
    assert "rpc_visible=true ORDER BY path" in cursor.query


def test_requested_non_catalog_path_is_rejected():
    try:
        select_catalog_paths(CatalogCursor(), "dev", ["gno.land/r/missing"], None)
    except RuntimeError as exc:
        assert str(exc) == "requested_path_not_visible"
    else:
        raise AssertionError("missing catalog path accepted")
