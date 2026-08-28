from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import api.app as module
from api.asset_classification import asset_classification_cache

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def fixture():
    base = {"rpc_visible": True, "call_count": 3, "successful_call_count": 2,
            "failed_call_count": 1, "last_activity_height": 10, "last_activity_at": NOW,
            "metadata_observed_height": 9, "total_file_bytes": 100}
    rows = [
        {**base, "path": "gno.land/r/demo/coin", "standard": "grc20", "qfunc_names": []},
        {**base, "path": "gno.land/r/demo/art", "standard": "grc721",
         "qfunc_names": ["BalanceOf", "OwnerOf", "TransferFrom"]},
    ]
    files = [
        {"path": rows[0]["path"], "filename": "main.gno", "file_kind": "gno_source",
         "content": 'grc20.NewToken(owner, "Coin", "COIN", 6)', "metadata_observed_height": 9},
        {"path": rows[1]["path"], "filename": "main.gno", "file_kind": "gno_source",
         "content": 'import "gno.land/p/vendor/grc721"\nvar nft=grc721.NewBasicNFT(0, cur, "Art", "ART")\nfunc OwnerOf() {}\nfunc Mint() {}',
         "metadata_observed_height": 9},
    ]
    source = {"chain_id": "pearl-1", "indexed_height": 10, "catalog_observed_height": 9,
              "metadata_observed_height": 9}
    return {"source": source, "candidates": rows, "files": files}


def call(mock_result=None, **overrides):
    module.app.state.api_config = SimpleNamespace(chain_id="pearl-1")
    defaults = {"limit": 50, "q": None, "standard": "all",
                "before_activity_height": None, "before_path": None}
    data = mock_result or fixture()
    with patch.object(module.database, "fetch_asset_candidates", return_value=data), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=data["files"]):
        return module.get_assets(**(defaults | overrides))


def setup_function():
    asset_classification_cache.clear()


def test_all_and_standard_filters_are_verified_and_native_is_absent():
    response = call()
    assert response.summary.model_dump() == {"asset_count": 2, "grc20_count": 1, "grc721_count": 1}
    assert {item.standard for item in response.items} == {"grc20", "grc721"}
    assert all(item.path != "gno.land/native/gnot" for item in response.items)
    assert [item.standard for item in call(standard="grc20").items] == ["grc20"]
    nft = call(standard="grc721").items[0]
    assert nft.standard == "grc721" and nft.token_count is None and nft.decimals is None


def test_asset_source_has_no_fabricated_activity_window():
    payload = call().model_dump()
    assert payload["source"] == {"chain_id": "pearl-1", "indexed_height": 10,
                                 "catalog_observed_height": 9, "metadata_observed_height": 9}
    assert "activity_window" not in payload["source"]
    assert "available_activity_windows" not in payload["source"]


def test_search_is_scoped_and_ordering_is_deterministic():
    assert [item.symbol for item in call(q="art").items] == ["ART"]
    assert call(q="coin", standard="grc721").items == []
    assert [item.path for item in call().items] == sorted(item.path for item in call().items)


def test_mixed_standard_path_fails_closed_without_identity_deduplication():
    data = fixture()
    grc20 = data["candidates"][0]
    data["candidates"].append({**grc20, "standard": "grc721",
                               "qfunc_names": ["Name", "Symbol", "OwnerOf", "TokenURI", "TransferFrom"]})
    response = call(data)
    assert response.summary.model_dump() == {"asset_count": 1, "grc20_count": 0, "grc721_count": 1}
    assert [item.path for item in response.items] == ["gno.land/r/demo/art"]


def test_static_classification_cache_reuses_all_filters_and_rejected_results():
    data = fixture()
    with patch.object(module.database, "fetch_asset_candidates", return_value=data), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=data["files"]) as files, \
         patch.object(module, "classify_grc721", wraps=module.classify_grc721) as classify:
        for standard in ("all", "grc721", "grc20"):
            module.get_assets(limit=50, q=None, standard=standard,
                              before_activity_height=None, before_path=None)
    assert classify.call_count == 1
    files.assert_called_once_with(chain_id="pearl-1",
                                  paths=["gno.land/r/demo/art", "gno.land/r/demo/coin"])

    asset_classification_cache.clear()
    rejected = fixture()
    rejected["files"][1]["content"] = 'import "gno.land/p/vendor/grc721"\nfunc OwnerOf() {}\nfunc Mint() {}'
    with patch.object(module.database, "fetch_asset_candidates", return_value=rejected), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=rejected["files"]), \
         patch.object(module, "classify_grc721", wraps=module.classify_grc721) as classify:
        for _ in range(2):
            module.get_assets(limit=50, q=None, standard="all",
                              before_activity_height=None, before_path=None)
    assert classify.call_count == 1


def test_cache_reclassifies_only_changed_revision_and_new_candidate():
    data = fixture()
    with patch.object(module.database, "fetch_asset_candidates", return_value=data), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=data["files"]), \
         patch.object(module, "classify_grc721", wraps=module.classify_grc721) as classify:
        module.get_assets(limit=50, q=None, standard="all", before_activity_height=None, before_path=None)
    assert classify.call_count == 1

    changed = fixture()
    changed["candidates"][1]["metadata_observed_height"] = 10
    changed["files"][1]["metadata_observed_height"] = 10
    with patch.object(module.database, "fetch_asset_candidates", return_value=changed), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=[changed["files"][1]]) as files, \
         patch.object(module, "classify_grc721", wraps=module.classify_grc721) as classify:
        module.get_assets(limit=50, q=None, standard="all", before_activity_height=None, before_path=None)
    assert classify.call_count == 1
    files.assert_called_once_with(chain_id="pearl-1", paths=["gno.land/r/demo/art"])

    new = fixture()
    new_row = {**new["candidates"][1], "path": "gno.land/r/demo/new-art"}
    new_file = {**new["files"][1], "path": new_row["path"]}
    new["candidates"].append(new_row); new["files"].append(new_file)
    with patch.object(module.database, "fetch_asset_candidates", return_value=new), \
         patch.object(module.database, "fetch_asset_candidate_files", return_value=[new_file]) as files, \
         patch.object(module, "classify_grc721", wraps=module.classify_grc721) as classify:
        module.get_assets(limit=50, q=None, standard="all", before_activity_height=None, before_path=None)
    assert classify.call_count == 1
    files.assert_called_once_with(chain_id="pearl-1", paths=["gno.land/r/demo/new-art"])
