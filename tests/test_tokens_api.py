from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import api.app as module

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def result(**source_overrides):
    base = {"rpc_visible": True, "call_count": 42, "successful_call_count": 40, "failed_call_count": 2,
            "last_activity_height": 90, "last_activity_at": NOW - timedelta(hours=2),
            "metadata_observed_height": 100, "total_file_bytes": 100}
    fixtures = [
        ("gno.land/r/gnoswap/test_token/test_sol", 'grc20.NewToken(owner, "Solana", "SOL", 9)'),
        ("gno.land/r/unknown/token", 'grc20.NewToken("Unknown Coin", "UNK", 6, 0, cur)'),
        ("gno.land/r/g1address/token", 'grc20.NewToken("Address Coin", "AC", 6, 0, cur)'),
        ("gno.land/r/demo/helper", 'func TotalSupply() {} // wrapper only'),
        ("gno.land/r/demo/factory", 'grc20.NewToken(name, symbol, decimals, id, cur)'),
    ]
    candidates, files = [], []
    for path, content in fixtures:
        candidates.append({**base, "path": path})
        files.append({"path": path, "filename": "main.gno", "file_kind": "gno_source",
                      "byte_count": len(content), "content": content})
    source = {"chain_id": "sapphire-1", "indexed_height": 110, "catalog_observed_height": 100,
              "metadata_observed_height": 100, "checkpoint_at": NOW, "activity_from_height": 1,
              "activity_through_height": 100, "activity_coverage_started_at": NOW - timedelta(days=2),
              "activity_checkpoint_at": NOW}
    source.update(source_overrides)
    return {"source": source, "candidates": candidates, "files": files}


def setup_module():
    module.app.state.api_config = SimpleNamespace(chain_id="sapphire-1")


def call(mock_result=None, **kwargs):
    defaults = {"limit": 50, "q": None, "before_activity_height": None, "before_path": None}
    with patch.object(module.database, "fetch_token_candidates", return_value=mock_result or result()) as fetch:
        response = module.get_tokens(**(defaults | kwargs))
    fetch.assert_called_once_with(chain_id="sapphire-1", candidate_limit=1001)
    return response


def test_only_source_verified_tokens_are_public_and_unknown_namespaces_remain_visible():
    response = call()
    assert response.summary.token_count == 3 and response.summary.active_24h_count == 3
    assert {item.namespace_key for item in response.items} == {"gnoswap", "unknown", "g1address"}
    assert all(item.identity_verified for item in response.items)
    assert not {"gno.land/r/demo/helper", "gno.land/r/demo/factory"} & {item.path for item in response.items}
    assert next(item for item in response.items if item.namespace_key == "unknown").application is None


def test_verified_identity_search_and_deterministic_cursor():
    sol = call(q="sOl").items
    assert len(sol) == 1 and (sol[0].name, sol[0].symbol, sol[0].decimals) == ("Solana", "SOL", 9)
    assert sol[0].application.display_name == "GnoSwap"
    assert len(call(q="UNKNOWN").items) == 1 and len(call(q="g1ADDRESS").items) == 1
    assert call(q="factory").items == []
    response = call(limit=2)
    assert [item.path for item in response.items] == sorted(item.path for item in response.items)
    assert response.pagination.next_before_activity_height == 90
    older = call(before_activity_height=90, before_path=response.items[-1].path)
    assert all(item.path > response.items[-1].path for item in older.items)


def test_active_24h_uses_completed_catalog_activity_checkpoint():
    # A complete catalog checkpoint may trail the continuously advancing indexer.
    assert call().summary.active_24h_count == 3
    assert call(result(activity_through_height=110)).summary.active_24h_count == 3
    for overrides in (
        {"activity_coverage_started_at": NOW - timedelta(hours=12)},
        {"activity_through_height": 111},
        {"activity_from_height": None, "activity_coverage_started_at": None},
        {"activity_checkpoint_at": None},
    ):
        assert call(result(**overrides)).summary.active_24h_count is None


def test_activity_after_checkpoint_and_unverified_candidates_do_not_count():
    data = result(activity_checkpoint_at=NOW - timedelta(hours=3))
    # All verified fixture activity is after this completed activity checkpoint.
    assert call(data).summary.active_24h_count == 0
    helper = next(row for row in data["candidates"] if row["path"].endswith("helper"))
    helper["last_activity_at"] = NOW - timedelta(hours=3)
    assert call(data).summary.active_24h_count == 0
