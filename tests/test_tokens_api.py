from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import api.app as module
from fastapi import HTTPException
import pytest

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
    source = {"chain_id": "pearl-1", "indexed_height": 110, "catalog_observed_height": 100,
              "metadata_observed_height": 100, "checkpoint_at": NOW, "call_index_from_height": 1,
              "call_index_through_height": 100, "call_index_coverage_started_at": NOW - timedelta(days=2),
              "call_index_checkpoint_at": NOW, "available_activity_hours": (24,)}
    source.update(source_overrides)
    return {"source": source, "candidates": candidates, "files": files,
            "activity_available": True, "activity": []}


def setup_module():
    module.app.state.api_config = SimpleNamespace(chain_id="pearl-1")


def call(mock_result=None, **kwargs):
    defaults = {"limit": 50, "q": None, "activity_window": "24h", "before_activity_height": None, "before_path": None}
    with patch.object(module.database, "fetch_token_candidates", return_value=mock_result or result()) as fetch:
        response = module.get_tokens(**(defaults | kwargs))
    fetch.assert_called_once_with(chain_id="pearl-1", window_hours=module.TOKEN_ACTIVITY_WINDOWS[kwargs.get("activity_window", "24h")], candidate_limit=1001)
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


def test_active_24h_uses_completed_call_index_checkpoint():
    # A complete call-index checkpoint may trail the continuously advancing indexer.
    assert call().summary.active_24h_count == 3
    assert call(result(call_index_through_height=110)).summary.active_24h_count == 3
    assert call(result(activity_from_height=None, activity_through_height=None)).summary.active_24h_count == 3
    for overrides in (
        {"call_index_coverage_started_at": NOW - timedelta(hours=12)},
        {"call_index_through_height": 111},
        {"call_index_from_height": None, "call_index_coverage_started_at": None},
        {"call_index_from_height": 101, "call_index_through_height": 100},
        {"call_index_checkpoint_at": None},
    ):
        assert call(result(**overrides)).summary.active_24h_count is None


def test_active_24h_closed_window_includes_exact_start_boundary():
    data = result()
    data["candidates"][0]["last_activity_at"] = NOW - timedelta(hours=24)
    assert call(data).summary.active_24h_count == 3


def test_activity_after_checkpoint_and_unverified_candidates_do_not_count():
    data = result(call_index_checkpoint_at=NOW - timedelta(hours=3))
    # All verified fixture activity is after this completed call-index checkpoint.
    assert call(data).summary.active_24h_count == 0
    helper = next(row for row in data["candidates"] if row["path"].endswith("helper"))
    helper["last_activity_at"] = NOW - timedelta(hours=3)
    assert call(data).summary.active_24h_count == 0


def test_top_activity_is_verified_global_and_not_historical_order():
    data = result()
    paths = [row["path"] for row in data["candidates"]]
    data["activity"] = [
        {"path": paths[0], "direct_call_count": 2, "last_activity_height": 80,
         "successful_call_count": 1, "failed_call_count": 0, "unknown_result_call_count": 1,
         "last_activity_at": NOW - timedelta(hours=1)},
        {"path": paths[1], "direct_call_count": 5, "last_activity_height": 70,
         "successful_call_count": 3, "failed_call_count": 1, "unknown_result_call_count": 1,
         "last_activity_at": NOW - timedelta(hours=2)},
        {"path": paths[3], "direct_call_count": 999, "last_activity_height": 99,
         "successful_call_count": 999, "failed_call_count": 0, "unknown_result_call_count": 0,
         "last_activity_at": NOW},
    ]
    data["candidates"][0]["call_count"] = 10000
    response = call(data, q="SOL", before_activity_height=None, before_path=None)
    assert [item.path for item in response.top_activity] == [paths[1], paths[0]]
    assert response.top_activity[0].successful_call_count == 3
    assert response.top_activity[0].failed_call_count == 1
    assert response.top_activity[0].unknown_result_call_count == 1
    assert response.top_activity[0].success_rate == .75
    assert [item.path for item in response.items] == [paths[0]]


def test_top_activity_unavailable_empty_and_deterministic_ties():
    data = result()
    data["activity_available"] = False
    assert call(data).top_activity is None
    data["activity_available"] = True
    assert call(data).top_activity == []
    verified_paths = [row["path"] for row in data["candidates"][:3]]
    data["activity"] = [{"path": path, "direct_call_count": 1,
                              "last_activity_height": 50,
                              "successful_call_count": 0, "failed_call_count": 0,
                              "unknown_result_call_count": 1,
                              "last_activity_at": NOW - timedelta(hours=1)}
                             for path in reversed(verified_paths)]
    assert [item.path for item in call(data).top_activity] == sorted(verified_paths)


@pytest.mark.parametrize(("window", "hours"), [("24h", 24), ("7d", 168), ("30d", 720)])
def test_supported_activity_windows_map_to_one_selected_grouped_query(window, hours):
    data = result(available_activity_hours=(24, 168, 720))
    response = call(data, activity_window=window, q="SOL")
    assert response.source.activity_window == window
    assert response.source.available_activity_windows == ["24h", "7d", "30d"]
    assert response.top_activity == []


def test_unsupported_activity_window_fails_closed_before_database():
    with patch.object(module.database, "fetch_token_candidates") as fetch:
        with pytest.raises(HTTPException) as error:
            module.get_tokens(limit=50, q=None, activity_window="2d",
                              before_activity_height=None, before_path=None)
    assert error.value.status_code == 422
    fetch.assert_not_called()


def test_incomplete_selected_window_is_unavailable_not_partial():
    data = result(available_activity_hours=(24,))
    data["activity_available"] = False
    response = call(data, activity_window="7d")
    assert response.source.available_activity_windows == ["24h"]
    assert response.top_activity is None


def test_selected_window_changes_global_activity_without_directory_filtering():
    twenty_four = result(available_activity_hours=(24, 168))
    seven_day = result(available_activity_hours=(24, 168))
    path = twenty_four["candidates"][0]["path"]
    base = {"path": path, "successful_call_count": 1, "failed_call_count": 0,
            "unknown_result_call_count": 0, "last_activity_height": 90,
            "last_activity_at": NOW - timedelta(hours=1)}
    twenty_four["activity"] = [{**base, "direct_call_count": 1}]
    seven_day["activity"] = [{**base, "direct_call_count": 8,
                               "successful_call_count": 7, "failed_call_count": 1}]
    short = call(twenty_four, activity_window="24h", q="UNKNOWN")
    long = call(seven_day, activity_window="7d", q="UNKNOWN")
    assert short.items[0].symbol == long.items[0].symbol == "UNK"
    assert short.top_activity[0].path == long.top_activity[0].path == path
    assert (short.top_activity[0].direct_call_count, long.top_activity[0].direct_call_count) == (1, 8)
