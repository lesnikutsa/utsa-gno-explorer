from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from indexer.realm_metadata_collector import CollectionRequest, collect_path_metadata
from indexer.realm_metadata_persistence import MetadataPersistenceError
from scripts.inspect_rpc import RpcError
from scripts import refresh_realm_metadata as cli
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
        self.execute_count = 0

    def execute(self, query, params):
        self.query = query
        self.execute_count += 1

    def fetchall(self):
        return [(99, PACKAGE, "package"), (99, REALM, "realm")]


def test_catalog_selection_deduplicates_filters_orders_and_limits():
    cursor = CatalogCursor()
    selection = select_catalog_paths(cursor, "dev", [REALM, REALM], 1)
    assert selection.observed_height == 99
    assert selection.paths == ((REALM, "realm"),)
    assert cursor.execute_count == 1
    assert "LEFT JOIN realm_catalog" in cursor.query
    assert "catalog.rpc_visible=true" in cursor.query
    assert "ORDER BY catalog.path" in cursor.query


def test_requested_non_catalog_path_is_rejected():
    try:
        select_catalog_paths(CatalogCursor(), "dev", ["gno.land/r/missing"], None)
    except RuntimeError as exc:
        assert str(exc) == "requested_path_not_visible"
    else:
        raise AssertionError("missing catalog path accepted")


class CoordinatorCursor:
    def __init__(self, connection):
        self.connection = connection
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=()):
        self.query = query
        if "pg_advisory_unlock" in query:
            self.connection.unlocked = True

    def fetchone(self):
        if "pg_try_advisory_lock" in self.query:
            return (self.connection.locked,)
        if "rpc_endpoints" in self.query:
            return (17,)
        raise AssertionError(self.query)

    def fetchall(self):
        assert "LEFT JOIN realm_catalog" in self.query
        return [(77, REALM, "realm"), (77, PACKAGE, "package")]


class CoordinatorConnection:
    def __init__(self, locked=True):
        self.locked = locked
        self.unlocked = False
        self.closed = False

    def cursor(self):
        return CoordinatorCursor(self)

    def commit(self):
        pass

    def close(self):
        self.closed = True


class CoordinatorDB:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection

    def get_selected_rpc_url(self, chain_id):
        return None


class CoordinatorClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def coordinator(monkeypatch, *, locked=True):
    connection = CoordinatorConnection(locked)
    database = CoordinatorDB(connection)
    client = CoordinatorClient()
    probe = SimpleNamespace(client=client, url="https://rpc.example/private", latest_height=100)
    states = []
    monkeypatch.setattr(cli, "load_config", lambda: SimpleNamespace(
        database_url="secret", chain_id="dev", rpc_urls=[probe.url], max_height_lag=5,
    ))
    monkeypatch.setattr(cli, "PostgresDatabase", lambda url: database)
    monkeypatch.setattr(cli, "_persist_state", lambda connection, state: states.append(state))
    monkeypatch.setattr(cli, "probe_rpc_endpoints", lambda *args, **kwargs: [probe])
    monkeypatch.setattr(cli, "suitable_rpc_probes", lambda probes: probes)
    return connection, client, states, probe


def result_for(request):
    return SimpleNamespace(snapshot=object(), status="complete")


def test_advisory_lock_already_held_exits_without_collection(monkeypatch):
    connection, client, states, _ = coordinator(monkeypatch, locked=False)
    called = []
    monkeypatch.setattr(cli, "collect_path_metadata", lambda *args: called.append(args))
    assert cli.main([]) == 1
    assert not called and not states
    assert connection.closed and not connection.unlocked
    assert not client.closed


def test_running_is_persisted_before_rpc_probe_and_no_rpc_becomes_failed(monkeypatch):
    connection, client, states, _ = coordinator(monkeypatch)

    def no_rpc(*args, **kwargs):
        assert [state.run_status for state in states] == ["running"]
        return []

    monkeypatch.setattr(cli, "probe_rpc_endpoints", no_rpc)
    assert cli.main([]) == 1
    assert [state.run_status for state in states] == ["running", "failed"]
    assert states[0].selected_path_count == 2 and states[0].observed_height == 77
    assert connection.closed and connection.unlocked


def test_all_paths_complete_advances_success_and_closes_resources(monkeypatch):
    connection, client, states, _ = coordinator(monkeypatch)
    monkeypatch.setattr(cli, "collect_path_metadata", lambda client, request: result_for(request))
    monkeypatch.setattr(cli, "publish_metadata_snapshot", lambda connection, snapshot: None)
    assert cli.main([]) == 0
    assert [state.run_status for state in states] == ["running", "complete"]
    assert states[-1].published_path_count == 2
    assert states[-1].last_successful_height == 77
    assert states[-1].last_successful_at is not None
    assert connection.closed and connection.unlocked and client.closed


def test_unexpected_collection_error_is_isolated_and_partial(monkeypatch, caplog):
    _, _, states, _ = coordinator(monkeypatch)
    calls = 0

    def collect(client, request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("sensitive collection payload")
        return result_for(request)

    monkeypatch.setattr(cli, "collect_path_metadata", collect)
    monkeypatch.setattr(cli, "publish_metadata_snapshot", lambda connection, snapshot: None)
    assert cli.main([]) == 2
    assert calls == 2 and states[-1].run_status == "partial"
    assert states[-1].last_successful_height is None
    assert "sensitive" not in caplog.text and "payload" not in caplog.text


def test_metadata_rejection_is_isolated_and_next_path_publishes(monkeypatch):
    _, _, states, _ = coordinator(monkeypatch)
    monkeypatch.setattr(cli, "collect_path_metadata", lambda client, request: result_for(request))
    calls = 0

    def publish(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MetadataPersistenceError("bounded")

    monkeypatch.setattr(cli, "publish_metadata_snapshot", publish)
    assert cli.main([]) == 2
    assert calls == 2 and states[-1].run_status == "partial"
    assert states[-1].published_path_count == states[-1].failed_path_count == 1
    assert states[-1].last_successful_height is None


def test_zero_publishable_paths_finishes_failed(monkeypatch):
    _, _, states, _ = coordinator(monkeypatch)
    failed_result = SimpleNamespace(snapshot=None, status="failed")
    monkeypatch.setattr(cli, "collect_path_metadata", lambda client, request: failed_result)
    assert cli.main([]) == 2
    assert states[-1].run_status == "failed"
    assert states[-1].published_path_count == 0 and states[-1].failed_path_count == 2
    assert states[-1].last_successful_height is None


def test_database_publication_failure_is_fatal_and_message_is_not_logged(monkeypatch, caplog):
    connection, client, states, _ = coordinator(monkeypatch)
    monkeypatch.setattr(cli, "collect_path_metadata", lambda client, request: result_for(request))

    def publish(*args):
        raise RuntimeError("database password and payload")

    monkeypatch.setattr(cli, "publish_metadata_snapshot", publish)
    assert cli.main([]) == 1
    assert [state.run_status for state in states] == ["running", "failed"]
    assert "password" not in caplog.text and "payload" not in caplog.text
    assert connection.closed and connection.unlocked and client.closed
