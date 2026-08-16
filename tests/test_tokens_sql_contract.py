import inspect

from api.database import (ASSET_DIRECTORY_CANDIDATES_SQL, MAX_TOKEN_DIRECTORY_SOURCE_BYTES, TOKEN_DIRECTORY_CANDIDATES_SQL,
                          TOKEN_DIRECTORY_ACTIVITY_SQL, TOKEN_DIRECTORY_FILES_SQL, TOKEN_DIRECTORY_SOURCE_SQL,
                          TOKEN_EXACT_CANDIDATE_SQL, TOKEN_EXACT_FILES_SQL, ApiDatabase)


def test_asset_discovery_adds_strict_grc721_without_changing_grc20_contract():
    assert "regexp_replace(imp.imported_path, '/+$', '') ~ '/(grc721|grc721v2)$'" in ASSET_DIRECTORY_CANDIDATES_SQL
    assert "UNION ALL" in ASSET_DIRECTORY_CANDIDATES_SQL
    grc20_branch, grc721_branch = ASSET_DIRECTORY_CANDIDATES_SQL.split("UNION ALL", 1)
    for name in ("Name", "Symbol", "OwnerOf", "TokenURI", "TransferFrom"):
        assert f'[{chr(123)}"FuncName":"{name}"{chr(125)}]' in grc721_branch
    assert "m.total_file_bytes > 0" in grc721_branch
    assert "path_kind='realm'" in ASSET_DIRECTORY_CANDIDATES_SQL
    for name in ("TotalSupply", "BalanceOf", "Transfer"):
        assert f'[{chr(123)}"FuncName":"{name}"{chr(125)}]' in grc20_branch
    assert "gno.land/p/demo/tokens/grc20" in grc20_branch


def test_discovery_sql_remains_conservative():
    assert "c.path_kind='realm'" in TOKEN_DIRECTORY_CANDIDATES_SQL
    assert "m.qfuncs_status='ok'" in TOKEN_DIRECTORY_CANDIDATES_SQL
    assert "imp.imported_path='gno.land/p/demo/tokens/grc20'" in TOKEN_DIRECTORY_CANDIDATES_SQL
    for name in ("TotalSupply", "BalanceOf", "Transfer"):
        assert f'[{chr(123)}"FuncName":"{name}"{chr(125)}]' in TOKEN_DIRECTORY_CANDIDATES_SQL


def test_source_query_is_separate_and_global_bound_precedes_content_fetch():
    assert "content" not in TOKEN_DIRECTORY_CANDIDATES_SQL.lower()
    assert "content" in TOKEN_DIRECTORY_FILES_SQL.lower()
    assert "file_kind='gno_source'" in TOKEN_DIRECTORY_FILES_SQL and "ANY(%s::text[])" in TOKEN_DIRECTORY_FILES_SQL
    method = inspect.getsource(ApiDatabase.fetch_token_candidates)
    assert method.index("MAX_TOKEN_DIRECTORY_SOURCE_BYTES") < method.index("cursor.execute(TOKEN_DIRECTORY_FILES_SQL")
    assert MAX_TOKEN_DIRECTORY_SOURCE_BYTES == 32 * 1024 * 1024


def test_exact_token_queries_are_conservative_and_path_bounded():
    assert "c.chain_id=%s AND c.path=%s" in TOKEN_EXACT_CANDIDATE_SQL
    assert "c.path_kind='realm'" in TOKEN_EXACT_CANDIDATE_SQL
    assert "m.qfuncs_status='ok'" in TOKEN_EXACT_CANDIDATE_SQL
    assert "imp.imported_path='gno.land/p/demo/tokens/grc20'" in TOKEN_EXACT_CANDIDATE_SQL
    for name in ("TotalSupply", "BalanceOf", "Transfer"):
        assert f'[{chr(123)}"FuncName":"{name}"{chr(125)}]' in TOKEN_EXACT_CANDIDATE_SQL
    assert "content" not in TOKEN_EXACT_CANDIDATE_SQL.lower()
    assert "chain_id=%s AND path=%s" in TOKEN_EXACT_FILES_SQL
    assert "file_kind='gno_source'" in TOKEN_EXACT_FILES_SQL
    method = inspect.getsource(ApiDatabase.fetch_verified_token_candidate)
    assert method.index("MAX_TOKEN_SOURCE_BYTES") < method.index("cursor.execute(TOKEN_EXACT_FILES_SQL")


def test_source_sql_uses_truthful_metadata_and_activity_coverage():
    assert "realm_metadata_refresh_state" not in TOKEN_DIRECTORY_SOURCE_SQL
    assert "NULL::bigint AS metadata_observed_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "call_state.from_height AS call_index_from_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "call_state.through_height AS call_index_through_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "coverage_start.time_utc AS call_index_coverage_started_at" in TOKEN_DIRECTORY_SOURCE_SQL


def test_activity_checkpoint_comes_from_call_index_through_height():
    assert "call_checkpoint.time_utc AS call_index_checkpoint_at" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "call_checkpoint.height=call_state.through_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "realm_call_index_state call_state" in TOKEN_DIRECTORY_SOURCE_SQL


def test_top_activity_is_one_bounded_grouped_query_with_closed_time_boundaries():
    assert "GROUP BY call.path" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "call.path=ANY(%s::text[])" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "call.block_height BETWEEN %s AND %s" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "block.time_utc >= %s" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "block.time_utc <= %s" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "LEFT JOIN transaction_execution_results result" in TOKEN_DIRECTORY_ACTIVITY_SQL
    for status in ("success", "failed"):
        assert f"result.execution_status='{status}'" in TOKEN_DIRECTORY_ACTIVITY_SQL
    assert "result.execution_status IS NULL" in TOKEN_DIRECTORY_ACTIVITY_SQL
    method = inspect.getsource(ApiDatabase.fetch_token_candidates)
    assert method.count("cursor.execute(TOKEN_DIRECTORY_ACTIVITY_SQL") == 1
    assert "checkpoint - timedelta(hours=window_hours)" in method
    assert "for hours in (24, 168, 720)" in method
