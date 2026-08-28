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
        self.params = params
        if "pg_advisory_unlock" in query:
            self.connection.unlocked = True

    def fetchone(self):
        if "pg_try_advisory_lock" in self.query:
            return (self.connection.locked,)
        if "rpc_endpoints" in self.query:
            endpoint_id = self.connection.endpoint_ids.get(self.params[1])
            return (endpoint_id,) if endpoint_id is not None else None
        raise AssertionError(self.query)

    def fetchall(self):
        assert "LEFT JOIN realm_catalog" in self.query
        return [(77, REALM, "realm"), (77, PACKAGE, "package")]


class CoordinatorConnection:
    def __init__(self, locked=True):
        self.locked = locked
        self.unlocked = False
        self.closed = False
        self.endpoint_ids = {"https://rpc.example/private": 17}

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


def failover_coordinator(monkeypatch, candidate_count=2):
    connection, _, states, first = coordinator(monkeypatch)
    probes = [first]
    for index in range(1, candidate_count):
        url = f"https://rpc-{index + 1}.example/private"
        connection.endpoint_ids[url] = 17 + index
        probes.append(SimpleNamespace(
            client=CoordinatorClient(), url=url, latest_height=100,
        ))
    monkeypatch.setattr(cli, "load_config", lambda: SimpleNamespace(
        database_url="secret", chain_id="dev", rpc_urls=[probe.url for probe in probes],
        max_height_lag=5,
    ))
    monkeypatch.setattr(cli, "probe_rpc_endpoints", lambda *args, **kwargs: probes)
    monkeypatch.setattr(cli, "suitable_rpc_probes", lambda candidates: candidates)
    return connection, states, probes


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


def test_qfile_listing_failover_publishes_from_second_rpc_at_fixed_height(monkeypatch, caplog):
    caplog.set_level("INFO", logger="realm_metadata_refresh")
    connection, states, probes = failover_coordinator(monkeypatch)
    requests = []
    published = []

    def collect(client, request):
        requests.append((client, request))
        if client is probes[0].client:
            return SimpleNamespace(snapshot=None, status="failed", failure_code="qfile_listing")
        snapshot = SimpleNamespace(source_rpc_endpoint_id=request.source_rpc_endpoint_id)
        return SimpleNamespace(snapshot=snapshot, status="complete", failure_code=None)

    monkeypatch.setattr(cli, "collect_path_metadata", collect)
    monkeypatch.setattr(cli, "publish_metadata_snapshot", lambda _, snapshot: published.append(snapshot))
    assert cli.main(["--path", REALM]) == 0
    assert len(published) == 1 and published[0].source_rpc_endpoint_id == 18
    assert [request.observed_height for _, request in requests] == [77, 77]
    assert states[-1].published_path_count == 1 and states[-1].failed_path_count == 0
    assert "metadata_rpc_failover" in caplog.text and "reason=qfile_listing" in caplog.text
    assert connection.unlocked and all(probe.client.closed for probe in probes)


def test_qfile_file_failure_uses_next_rpc(monkeypatch):
    _, states, probes = failover_coordinator(monkeypatch)
    clients = []

    def collect(client, request):
        clients.append(client)
        if client is probes[0].client:
            return SimpleNamespace(snapshot=None, status="failed", failure_code="qfile_file")
        return SimpleNamespace(snapshot=object(), status="complete", failure_code=None)

    monkeypatch.setattr(cli, "collect_path_metadata", collect)
    monkeypatch.setattr(cli, "publish_metadata_snapshot", lambda *_: None)
    assert cli.main(["--path", REALM]) == 0
    assert clients == [probes[0].client, probes[1].client]
    assert states[-1].published_path_count == 1


def test_all_rpc_required_failures_count_path_once_and_attempts_are_bounded(monkeypatch):
    _, states, probes = failover_coordinator(monkeypatch, candidate_count=3)
    calls = []

    def collect(client, request):
        calls.append((client, request.observed_height))
        return SimpleNamespace(snapshot=None, status="failed", failure_code="qfile_file")

    monkeypatch.setattr(cli, "collect_path_metadata", collect)
    assert cli.main(["--path", REALM]) == 2
    assert calls == [(probe.client, 77) for probe in probes]
    assert states[-1].published_path_count == 0
    assert states[-1].failed_path_count == 1


def test_publishable_partial_snapshot_does_not_fail_over(monkeypatch):
    _, states, probes = failover_coordinator(monkeypatch)
    calls = []
    snapshot = object()

    def collect(client, request):
        calls.append(client)
        return SimpleNamespace(snapshot=snapshot, status="partial", failure_code=None)

    published = []
    monkeypatch.setattr(cli, "collect_path_metadata", collect)
    monkeypatch.setattr(cli, "publish_metadata_snapshot", lambda _, value: published.append(value))
    assert cli.main(["--path", REALM]) == 0
    assert calls == [probes[0].client] and published == [snapshot]
    assert states[-1].published_path_count == 1


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
