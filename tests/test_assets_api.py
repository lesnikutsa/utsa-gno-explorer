from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import api.app as module

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
         "content": 'grc20.NewToken(owner, "Coin", "COIN", 6)'},
        {"path": rows[1]["path"], "filename": "main.gno", "file_kind": "gno_source",
         "content": 'import "gno.land/p/demo/tokens/grc721"\nvar nft=grc721.NewBasicNFT(owner, "Art", "ART")'},
    ]
    source = {"chain_id": "sapphire-1", "indexed_height": 10, "catalog_observed_height": 9,
              "metadata_observed_height": 9}
    return {"source": source, "candidates": rows, "files": files}


def call(**overrides):
    module.app.state.api_config = SimpleNamespace(chain_id="sapphire-1")
    defaults = {"limit": 50, "q": None, "standard": "all",
                "before_activity_height": None, "before_path": None}
    with patch.object(module.database, "fetch_asset_candidates", return_value=fixture()):
        return module.get_assets(**(defaults | overrides))


def test_all_and_standard_filters_are_verified_and_native_is_absent():
    response = call()
    assert response.summary.model_dump() == {"asset_count": 2, "grc20_count": 1, "grc721_count": 1}
    assert {item.standard for item in response.items} == {"grc20", "grc721"}
    assert all(item.path != "gno.land/native/gnot" for item in response.items)
    assert [item.standard for item in call(standard="grc20").items] == ["grc20"]
    nft = call(standard="grc721").items[0]
    assert nft.standard == "grc721" and nft.token_count is None and nft.decimals is None


def test_search_is_scoped_and_ordering_is_deterministic():
    assert [item.symbol for item in call(q="art").items] == ["ART"]
    assert call(q="coin", standard="grc721").items == []
    assert [item.path for item in call().items] == sorted(item.path for item in call().items)
