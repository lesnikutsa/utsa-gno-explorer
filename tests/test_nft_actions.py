from datetime import datetime, timedelta, timezone

import pytest

from api.nft_actions import classify_nft_action


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
