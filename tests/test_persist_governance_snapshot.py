from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from governance.gno import DEFAULT_REALM, GovernanceDiscovery, GovernanceSource
from indexer.governance_persistence import GovernancePersistenceResult, IncompleteGovernanceSnapshot
from scripts import persist_governance_snapshot as cli


def configure(monkeypatch, realm_env=""):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db/name")
    monkeypatch.setenv("GNO_GOVERNANCE_REALM", realm_env)
    loaded = Mock(); monkeypatch.setattr(cli, "load_dotenv", loaded)
    monkeypatch.setattr(cli, "configured_chain_id", lambda: "topaz-1")
    monkeypatch.setattr(cli, "configured_rpc_urls", lambda: ["https://token@rpc.invalid"])
    monkeypatch.setattr(cli, "configured_max_height_lag", lambda: 3)
    client = SimpleNamespace(base_url="https://token@rpc.invalid")
    select = Mock(return_value=SimpleNamespace(client=client, latest_height=123))
    monkeypatch.setattr(cli, "select_rpc", select)
    discovery = GovernanceDiscovery(GovernanceSource("topaz-1", client.base_url, 123, realm_env or DEFAULT_REALM), True, 1, (), (), {})
    discover = Mock(return_value=discovery); monkeypatch.setattr(cli, "discover_governance", discover)
    persist = Mock(return_value=GovernancePersistenceResult("applied", 123, 1, 0, 0))
    monkeypatch.setattr(cli.PostgresDatabase, "persist_governance_snapshot", persist)
    return loaded, select, discover, persist


def test_run_loads_env_selects_rpc_and_captures_full_raw(monkeypatch, capsys):
    loaded, select, discover, persist = configure(monkeypatch)
    assert cli.main([]) == 0
    loaded.assert_called_once_with()
    select.assert_called_once_with(["https://token@rpc.invalid"], "topaz-1", 3, 10)
    assert discover.call_args.kwargs == {"capture_raw": True}
    source = discover.call_args.args[1]
    assert source.observed_height == 123 and source.realm_path == DEFAULT_REALM
    persist.assert_called_once()
    assert "action=applied" in capsys.readouterr().out


@pytest.mark.parametrize("arguments,env,expected", [([], "", DEFAULT_REALM), ([], "gno.land/r/env", "gno.land/r/env"), (["--realm", "gno.land/r/cli"], "gno.land/r/env", "gno.land/r/cli")])
def test_realm_priority(monkeypatch, arguments, env, expected):
    _, _, discover, _ = configure(monkeypatch, env)
    assert cli.main(arguments) == 0
    assert discover.call_args.args[1].realm_path == expected


def test_database_url_required_without_leak(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False); monkeypatch.setattr(cli, "load_dotenv", Mock())
    assert cli.main([]) == 1
    assert "DATABASE_URL is required" in capsys.readouterr().err


def test_expected_persistence_failure_has_no_traceback(monkeypatch, capsys):
    configure(monkeypatch)
    monkeypatch.setattr(cli.PostgresDatabase, "persist_governance_snapshot", Mock(side_effect=IncompleteGovernanceSnapshot("unparsed votes")))
    assert cli.main([]) == 1
    error = capsys.readouterr().err
    assert "unparsed votes" in error and "Traceback" not in error and "secret" not in error


def test_rpc_failure_redacts_endpoint(monkeypatch, capsys):
    configure(monkeypatch)
    monkeypatch.setattr(cli, "select_rpc", Mock(side_effect=OSError("https://token@rpc.invalid failed")))
    assert cli.main([]) == 1
    assert capsys.readouterr().err == "Governance persistence failed: rpc_error\n"


def test_unchanged_output(monkeypatch, capsys):
    configure(monkeypatch)
    monkeypatch.setattr(cli.PostgresDatabase, "persist_governance_snapshot", Mock(return_value=GovernancePersistenceResult("unchanged", 123, 1, 0, 0)))
    assert cli.main([]) == 0
    assert "action=unchanged" in capsys.readouterr().out
