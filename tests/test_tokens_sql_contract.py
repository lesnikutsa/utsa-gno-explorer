import inspect

from api.database import (MAX_TOKEN_DIRECTORY_SOURCE_BYTES, TOKEN_DIRECTORY_CANDIDATES_SQL,
                          TOKEN_DIRECTORY_FILES_SQL, TOKEN_DIRECTORY_SOURCE_SQL, ApiDatabase)


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


def test_source_sql_uses_truthful_metadata_and_activity_coverage():
    assert "realm_metadata_refresh_state" not in TOKEN_DIRECTORY_SOURCE_SQL
    assert "NULL::bigint AS metadata_observed_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "activity_from_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "activity_through_height" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "coverage_start.time_utc" in TOKEN_DIRECTORY_SOURCE_SQL


def test_activity_checkpoint_comes_from_catalog_through_height():
    assert "activity_checkpoint.time_utc AS activity_checkpoint_at" in TOKEN_DIRECTORY_SOURCE_SQL
    assert "activity_checkpoint.height=catalog.activity_through_height" in TOKEN_DIRECTORY_SOURCE_SQL
