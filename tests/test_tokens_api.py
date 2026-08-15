from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import api.app as module

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def result(**source_overrides):
    base = {"rpc_visible": True, "call_count": 42, "successful_call_count": 40, "failed_call_count": 2,
            "last_activity_height": 90, "last_activity_at": NOW - timedelta(hours=2),
            "metadata_observed_height": 100, "total_file_bytes": 100}
    candidates, files = [], []
    for path, content in [
        ("gno.land/r/gnoswap/test_token/test_sol", 'grc20.NewToken(owner, "Solana", "SOL", 9)'),
        ("gno.land/r/unknown/token", 'grc20.NewToken(owner, getName(), "UNK", 6)'),
        ("gno.land/r/g1address/token", 'grc20.NewToken(owner, "Address Coin", "AC", 6)'),
    ]:
        candidates.append({**base, "path": path})
        files.append({"path": path, "filename": "main.gno", "file_kind": "gno_source", "byte_count": len(content), "content": content})
    source = {"chain_id": "sapphire-1", "indexed_height": 110, "catalog_observed_height": 100,
              "metadata_observed_height": 100, "checkpoint_at": NOW, "activity_from_height": 1,
              "activity_through_height": 110, "activity_coverage_started_at": NOW - timedelta(days=2)}
    source.update(source_overrides)
    return {"source": source, "candidates": candidates, "files": files}


def setup_module():
    module.app.state.api_config = SimpleNamespace(chain_id="sapphire-1")


def call(**kwargs):
    defaults = {"limit": 50, "q": None, "before_activity_height": None, "before_path": None}
    with patch.object(module.database, "fetch_token_candidates", return_value=result()) as fetch:
        response = module.get_tokens(**(defaults | kwargs))
    fetch.assert_called_once_with(chain_id="sapphire-1", candidate_limit=1001)
    return response


def test_unknown_and_address_namespaces_are_not_filtered_and_summary_is_checkpoint_anchored():
    response = call()
    assert response.summary.token_count == 3 and response.summary.active_24h_count == 3
    assert {item.namespace_key for item in response.items} == {"gnoswap", "unknown", "g1address"}
    assert next(item for item in response.items if item.namespace_key == "unknown").application is None


def test_verified_identity_and_case_insensitive_search_fields():
    sol = call(q="sOl").items
    assert len(sol) == 1 and sol[0].name == "Solana" and sol[0].symbol == "SOL" and sol[0].decimals == 9
    assert sol[0].identity_verified and sol[0].application.display_name == "GnoSwap"
    assert len(call(q="UNKNOWN").items) == 1
    assert len(call(q="g1ADDRESS").items) == 1


def test_unverified_identity_is_null_and_cursor_order_is_deterministic():
    response = call(limit=2)
    assert [item.path for item in response.items] == sorted(item.path for item in response.items)
    assert response.pagination.next_before_activity_height == 90
    unknown = call(q="unknown").items[0]
    assert (unknown.name, unknown.symbol, unknown.decimals, unknown.identity_verified) == (None, None, None, False)
    older = call(before_activity_height=90, before_path=response.items[-1].path)
    assert all(item.path > response.items[-1].path for item in older.items)


def test_active_24h_requires_complete_coverage():
    assert call().summary.active_24h_count == 3
    for overrides in (
        {"activity_coverage_started_at": NOW - timedelta(hours=12)},
        {"activity_through_height": 109},
        {"activity_from_height": None, "activity_coverage_started_at": None},
    ):
        with patch.object(module.database, "fetch_token_candidates", return_value=result(**overrides)):
            response = module.get_tokens(limit=50, q=None, before_activity_height=None, before_path=None)
        assert response.summary.active_24h_count is None
