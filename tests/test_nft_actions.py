from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from types import SimpleNamespace
from unittest.mock import patch

import api.app as app_module
from api.asset_classification import StaticAssetClassification, asset_classification_cache
from api.nft_actions import classify_nft_action

PATH = "gno.land/r/example/collection"
NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def candidate(revision=10):
    return {"path": PATH, "standard": "grc721", "metadata_observed_height": revision,
            "qfunc_names": ["BalanceOf", "OwnerOf", "TransferFrom"], "total_file_bytes": 100}


def source_file(revision=10, *, verified=True):
    constructor = 'var nft=grc721.NewBasicNFT(0, cur, "Art", "ART")' if verified else ""
    return {"path": PATH, "filename": "main.gno", "file_kind": "gno_source", "byte_count": 100,
            "metadata_observed_height": revision,
            "content": f'import "gno.land/p/vendor/grc721"\n{constructor}\nfunc OwnerOf() {{}}\nfunc Mint() {{}}'}


def activity_result(*, available=True):
    row = {"path": PATH, "action_count": 6, "mint_count": 1, "transfer_count": 2,
           "approval_count": 2, "burn_count": 1, "last_action": "burn",
           "last_action_function": "Burn", "last_action_at": NOW, "last_action_height": 20}
    return {"source": {"call_index_checkpoint_at": NOW}, "available": available,
            "items": [row] if available else []}


def call_activity(*, candidates=None, files=None, activity=None):
    app_module.app.state.api_config = SimpleNamespace(chain_id="test-chain")
    candidates = [candidate()] if candidates is None else candidates
    files = [source_file()] if files is None else files
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": candidates}), \
         patch.object(app_module.database, "fetch_asset_candidate_files", return_value=files) as fetch_files, \
         patch.object(app_module.database, "fetch_nft_activity",
                      return_value=activity_result() if activity is None else activity) as fetch_activity:
        response = app_module.get_nft_activity(paths=[PATH], window="24h")
    return response, fetch_files, fetch_activity


def setup_function():
    asset_classification_cache.clear()
    app_module.app.state.api_config = SimpleNamespace(chain_id="test-chain")


def test_exact_case_sensitive_nft_action_classification():
    assert {name: classify_nft_action(name) for name in (
        "Mint", "TransferFrom", "SafeTransferFrom", "Approve", "SetApprovalForAll", "Burn"
    )} == {
        "Mint": "mint", "TransferFrom": "transfer", "SafeTransferFrom": "transfer",
        "Approve": "approval", "SetApprovalForAll": "approval", "Burn": "burn",
    }
    for name in ("mint", "MintSpecial", "Transfer", "BurnSomething"):
        assert classify_nft_action(name) is None


def test_nft_activity_sql_is_success_only_bounded_and_uses_no_rpc():
    from api.database import NFT_ACTIVITY_SQL
    assert "result.execution_status='success'" in NFT_ACTIVITY_SQL
    assert "call.block_height BETWEEN %s AND %s" in NFT_ACTIVITY_SQL
    assert "block.time_utc >= %s AND block.time_utc <= %s" in NFT_ACTIVITY_SQL
    assert "JOIN mapping ON mapping.function_name=call.function_name" in NFT_ACTIVITY_SQL
    assert "result.execution_status='success'" in NFT_ACTIVITY_SQL
    assert "row_number() OVER (PARTITION BY path ORDER BY block_height DESC,tx_index DESC,message_index DESC)" in NFT_ACTIVITY_SQL
    assert "count(*) FILTER (WHERE action='mint')" in NFT_ACTIVITY_SQL
    assert "count(*) FILTER (WHERE action='transfer')" in NFT_ACTIVITY_SQL
    assert "count(*) FILTER (WHERE action='approval')" in NFT_ACTIVITY_SQL
    assert "count(*) FILTER (WHERE action='burn')" in NFT_ACTIVITY_SQL
    assert "rpc" not in NFT_ACTIVITY_SQL.casefold()


def test_checkpoint_coverage_must_be_continuous_through_indexed_height():
    from api.database import complete_realm_call_coverage_bounds
    checkpoint = datetime(2026, 8, 18, tzinfo=timezone.utc)
    source = {"chain_id": "chain", "call_chain_id": "chain", "indexed_height": 20,
              "call_index_from_height": 1, "call_index_through_height": 20,
              "call_index_checkpoint_at": checkpoint,
              "call_index_coverage_started_at": checkpoint - timedelta(hours=25)}
    assert complete_realm_call_coverage_bounds(source, "chain") == (1, 20)
    assert complete_realm_call_coverage_bounds(source | {"call_index_through_height": 19}, "chain") is None


def test_nft_path_query_is_bounded_before_database_access():
    from api.database import ApiDatabase
    database = ApiDatabase()
    database.pool = object()
    with pytest.raises(ValueError, match="bounded"):
        database.fetch_nft_activity(chain_id="chain", paths=[f"gno.land/r/demo/{index}" for index in range(51)])


def test_api_exposes_aggregate_and_latest_recognized_successful_action():
    response, _, fetch_activity = call_activity()
    item = response.items[0]
    assert (item.mint_count, item.transfer_count, item.approval_count, item.burn_count,
            item.action_count) == (1, 2, 2, 1, 6)
    assert (item.last_action, item.last_action_function, item.last_action_at,
            item.last_action_height) == ("burn", "Burn", "2026-08-18T00:00:00Z", 20)
    fetch_activity.assert_called_once_with(chain_id="test-chain", paths=[PATH])


def test_api_returns_explicit_zeroed_unavailable_item_for_incomplete_coverage():
    response, _, _ = call_activity(activity=activity_result(available=False))
    item = response.items[0]
    assert item.available is False
    assert (item.action_count, item.mint_count, item.transfer_count,
            item.approval_count, item.burn_count) == (0, 0, 0, 0, 0)
    assert (item.last_action, item.last_action_function, item.last_action_at,
            item.last_action_height) == (None, None, None, None)


def test_warm_matching_revision_skips_source_fetch_and_reuses_verified_cache():
    key = ("test-chain", PATH, "grc721", 10)
    asset_classification_cache.put(key, StaticAssetClassification(True, "Art", "ART", None, "verified"))
    response, fetch_files, _ = call_activity(files=[])
    assert response.items[0].available is True
    fetch_files.assert_not_called()


def test_cold_request_fetches_once_populates_cache_and_revision_change_reclassifies():
    _, first_fetch, _ = call_activity()
    first_fetch.assert_called_once_with(chain_id="test-chain", paths=[PATH])
    assert asset_classification_cache.get(("test-chain", PATH, "grc721", 10)).verified is True
    _, warm_fetch, _ = call_activity(files=[])
    warm_fetch.assert_not_called()
    _, changed_fetch, _ = call_activity(candidates=[candidate(11)], files=[source_file(11)])
    changed_fetch.assert_called_once_with(chain_id="test-chain", paths=[PATH])
    assert asset_classification_cache.get(("test-chain", PATH, "grc721", 11)).verified is True


def test_rejected_cache_is_reused_without_source_fetch():
    key = ("test-chain", PATH, "grc721", 10)
    asset_classification_cache.put(key, StaticAssetClassification(False, None, None, None, "unverified"))
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": [candidate()]}), \
         patch.object(app_module.database, "fetch_asset_candidate_files") as fetch_files, \
         pytest.raises(HTTPException) as error:
        app_module.get_nft_activity(paths=[PATH], window="24h")
    assert error.value.status_code == 404
    fetch_files.assert_not_called()


def test_cold_rejection_is_cached_and_reused():
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": [candidate()]}), \
         patch.object(app_module.database, "fetch_asset_candidate_files",
                      return_value=[source_file(verified=False)]) as cold_fetch, \
         pytest.raises(HTTPException):
        app_module.get_nft_activity(paths=[PATH], window="24h")
    cold_fetch.assert_called_once_with(chain_id="test-chain", paths=[PATH])
    cached = asset_classification_cache.get(("test-chain", PATH, "grc721", 10))
    assert cached is not None and cached.verified is False
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": [candidate()]}), \
         patch.object(app_module.database, "fetch_asset_candidate_files") as warm_fetch, \
         pytest.raises(HTTPException):
        app_module.get_nft_activity(paths=[PATH], window="24h")
    warm_fetch.assert_not_called()


def test_stale_source_revision_is_never_cached_as_current():
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": [candidate(11)]}), \
         patch.object(app_module.database, "fetch_asset_candidate_files", return_value=[source_file(10)]), \
         pytest.raises(HTTPException) as error:
        app_module.get_nft_activity(paths=[PATH], window="24h")
    assert error.value.status_code == 404
    assert asset_classification_cache.get(("test-chain", PATH, "grc721", 11)) is None


def test_activity_path_validation_and_identity_rejection():
    with pytest.raises(HTTPException) as duplicate:
        app_module.get_nft_activity(paths=[PATH, PATH], window="24h")
    assert duplicate.value.status_code == 422
    with pytest.raises(HTTPException) as too_many:
        app_module.get_nft_activity(paths=[f"gno.land/r/example/{index}" for index in range(51)], window="24h")
    assert too_many.value.status_code == 422
    with pytest.raises(HTTPException) as package:
        app_module.get_nft_activity(paths=["gno.land/p/example/package"], window="24h")
    assert package.value.status_code == 422
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": []}), \
         patch.object(app_module.database, "fetch_asset_candidate_files", return_value=[]), \
         pytest.raises(HTTPException) as unverified:
        app_module.get_nft_activity(paths=[PATH], window="24h")
    assert unverified.value.status_code == 404


def test_ambiguous_grc20_grc721_path_is_rejected_without_classification():
    ambiguous = [candidate(), {**candidate(), "standard": "grc20"}]
    with patch.object(app_module.database, "fetch_asset_candidates",
                      return_value={"source": {}, "candidates": ambiguous}), \
         patch.object(app_module.database, "fetch_asset_candidate_files") as fetch_files, \
         pytest.raises(HTTPException) as error:
        app_module.get_nft_activity(paths=[PATH], window="24h")
    assert error.value.status_code == 404
    fetch_files.assert_not_called()
