from types import SimpleNamespace

from scripts import check_runtime


def snapshot(**changes):
    values = dict(
        indexed_height=100, catalog_state=(99, 2), catalog_counts=(1, 1, 2),
        call_state=(1, 100), call_rows=7, metadata_rows=2,
        metadata_statuses=(("complete", 1), ("partial", 1)), metadata_height=99,
        metadata_refresh=(99, "partial"),
    )
    values.update(changes)
    return check_runtime.DatabaseSnapshot(**values)


def run(capsys, *, unit=None, db=None, api=None, config=None):
    healthy_unit = lambda name: {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}
    code = check_runtime.run(
        config_loader=lambda: config or SimpleNamespace(database_url="postgresql://user:secret@db/name", chain_id="pearl-1", rpc_urls=["https://token@rpc.invalid"]),
        unit_inspector=unit or healthy_unit,
        database_inspector=lambda *_: db or snapshot(),
        api_inspector=api or (lambda _: {"status": "ok", "database": "ok", "chain_id": "pearl-1", "indexed_height": 100, "indexer_lag": 0}),
    )
    return code, capsys.readouterr().out


def test_healthy_runtime_and_partial_metadata(capsys):
    code, output = run(capsys)
    assert code == 0
    assert "Result: HEALTHY" in output and "partial=1" in output


def test_inactive_long_running_service_fails(capsys):
    def units(name):
        return {"LoadState": "loaded", "ActiveState": "inactive" if name == check_runtime.SERVICES[1] else "active", "UnitFileState": "enabled"}
    code, output = run(capsys, unit=units)
    assert code == 1 and "utsa-gno-indexer.service: inactive" in output


def test_installed_inactive_active_and_activating_oneshots_are_healthy(capsys):
    def units(name):
        states = dict(zip(check_runtime.SCHEDULED_SERVICES, ("inactive", "active", "activating", "inactive")))
        active = states.get(name, "active")
        return {"LoadState": "loaded", "ActiveState": active, "UnitFileState": "enabled"}
    code, output = run(capsys, unit=units)
    assert code == 0
    assert f"{check_runtime.SCHEDULED_SERVICES[0]}: installed, inactive" in output
    assert f"{check_runtime.SCHEDULED_SERVICES[1]}: installed, active" in output
    assert f"{check_runtime.SCHEDULED_SERVICES[2]}: installed, activating" in output


def test_failed_oneshot_is_runtime_failure(capsys):
    failed = check_runtime.SCHEDULED_SERVICES[0]
    def units(name):
        return {"LoadState": "loaded", "ActiveState": "failed" if name == failed else "active", "UnitFileState": "enabled"}
    code, output = run(capsys, unit=units)
    assert code == 1
    assert f"{failed}: installed, failed" in output


def test_unexpected_oneshot_active_state_is_runtime_failure(capsys):
    unexpected = check_runtime.SCHEDULED_SERVICES[1]
    def units(name):
        return {"LoadState": "loaded", "ActiveState": "deactivating" if name == unexpected else "active", "UnitFileState": "enabled"}
    code, output = run(capsys, unit=units)
    assert code == 1
    assert f"{unexpected}: installed, deactivating" in output


def test_missing_oneshot_fails_even_when_timer_is_healthy(capsys):
    missing = check_runtime.SCHEDULED_SERVICES[2]
    def units(name):
        return {
            "LoadState": "not-found" if name == missing else "loaded",
            "ActiveState": "inactive" if name == missing else "active",
            "UnitFileState": "enabled",
        }
    code, output = run(capsys, unit=units)
    assert code == 1
    assert f"{missing}: not installed" in output
    assert all(f"{timer}: enabled, active" in output for timer in check_runtime.TIMERS)


def test_missing_or_disabled_timer_fails(capsys):
    def units(name):
        if name == check_runtime.TIMERS[0]:
            return {"LoadState": "not-found", "ActiveState": "inactive", "UnitFileState": ""}
        if name == check_runtime.TIMERS[1]:
            return {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "disabled"}
        return {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}
    code, output = run(capsys, unit=units)
    assert code == 1 and "not installed" in output and "disabled, active" in output


def test_api_unreachable_and_chain_mismatch(capsys):
    code, output = run(capsys, api=lambda _: (_ for _ in ()).throw(OSError("postgresql://leak:secret@host")))
    assert code == 1 and "OSError" in output and "secret" not in output
    code, output = run(capsys, api=lambda _: {"status": "ok", "database": "ok", "chain_id": "wrong", "indexed_height": 100, "indexer_lag": 0})
    assert code == 1 and "does not match" in output


def test_health_url_uses_api_bind_defaults():
    assert check_runtime.resolve_health_url({}) == "http://127.0.0.1:18180/api/health"


def test_health_url_honors_non_default_port():
    assert check_runtime.resolve_health_url({"API_BIND_PORT": "28180"}) == "http://127.0.0.1:28180/api/health"


def test_health_url_replaces_wildcard_hosts_with_loopback():
    for host in ("0.0.0.0", "::"):
        assert check_runtime.resolve_health_url({"API_BIND_HOST": host}) == "http://127.0.0.1:18180/api/health"


def test_missing_database_config_is_inspection_error_and_secrets_stay_hidden(capsys, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://visible:password@host/db")
    monkeypatch.setenv("GNO_RPC_URLS", "https://token@rpc.example")
    code, output = run(capsys, config=SimpleNamespace(database_url="", chain_id="pearl-1", rpc_urls=[]))
    assert code == 2
    assert "password" not in output and "rpc.example" not in output and "DATABASE_URL" not in output


def test_existing_checkpoint_without_call_state_fails(capsys):
    code, output = run(capsys, db=snapshot(call_state=None, call_rows=9))
    assert code == 1 and "coverage state is missing" in output


def test_failed_metadata_refresh_fails_runtime(capsys):
    code, output = run(capsys, db=snapshot(metadata_refresh=(99, "failed")))
    assert code == 1
    assert "refresh #99 failed" in output


def test_running_metadata_refresh_warns_without_failing(capsys):
    code, output = run(capsys, db=snapshot(metadata_refresh=(99, "running")))
    assert code == 0
    assert "[WARN] Metadata" in output


def test_valid_coverage_uses_one_consistent_snapshot(capsys):
    calls = 0
    def database(*_):
        nonlocal calls
        calls += 1
        return snapshot(indexed_height=101, call_state=(1, 101))
    code = check_runtime.run(
        config_loader=lambda: SimpleNamespace(database_url="configured", chain_id="pearl-1"),
        unit_inspector=lambda _: {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"},
        database_inspector=database,
        api_inspector=lambda _: {"status": "ok", "database": "ok", "chain_id": "pearl-1", "indexed_height": 102, "indexer_lag": 0},
    )
    output = capsys.readouterr().out
    assert code == 0 and calls == 1 and "#1 -> #101, contiguous" in output
    assert "heights differ" in output


def test_database_failure_is_sanitized(capsys):
    def database(*_): raise RuntimeError("postgresql://user:secret@host/db")
    code = check_runtime.run(
        config_loader=lambda: SimpleNamespace(database_url="postgresql://user:secret@host/db", chain_id="pearl-1"),
        unit_inspector=lambda _: {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"},
        database_inspector=database,
        api_inspector=lambda _: {"status": "ok", "database": "ok", "chain_id": "pearl-1", "indexed_height": 1, "indexer_lag": 0},
    )
    output = capsys.readouterr().out
    assert code == 1 and "RuntimeError" in output and "secret" not in output
