from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import api.app as module
from api.token_supply import TokenSupplyCache, decimal_amount, parse_total_supply, token_supply_cache


PATH = "gno.land/r/demo/token"


def directory_result(path=PATH, source='grc20.NewToken("Demo", "DMT", 6, 0, cur)'):
    return {
        "source": {"chain_id": "sapphire-1"},
        "candidates": [{"path": path}],
        "files": [{"path": path, "filename": "token.gno", "file_kind": "gno_source",
                   "content": source}],
    }


@pytest.fixture(autouse=True)
def configure():
    module.app.state.api_config = SimpleNamespace(
        chain_id="sapphire-1", rpc_urls=("https://rpc.example",),
    )
    token_supply_cache.clear()


def call(result=None):
    with patch.object(module.database, "fetch_token_candidates", return_value=result or directory_result()), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value="https://selected.example"), \
         patch.object(module, "query_total_supply", return_value="300000000000000") as query:
        response = module.get_token_supply(PATH)
    return response, query


def test_verified_token_gets_fixed_runtime_total_supply():
    response, query = call()
    assert response.model_dump() == {
        "path": PATH, "raw_total_supply": "300000000000000", "decimals": 6,
        "total_supply": "300000000", "symbol": "DMT", "available": True,
    }
    query.assert_called_once_with(rpc_url="https://selected.example", path=PATH)


def test_arbitrary_or_unverified_realm_is_rejected_before_rpc():
    with patch.object(module.database, "fetch_token_candidates", return_value=directory_result()), \
         patch.object(module, "query_total_supply") as query:
        with pytest.raises(HTTPException) as error:
            module.get_token_supply("gno.land/r/demo/not_a_token")
    assert error.value.status_code == 404
    query.assert_not_called()

    with patch.object(module.database, "fetch_token_candidates",
                      return_value=directory_result(source="func TotalSupply() uint64 { return 9 }")), \
         patch.object(module, "query_total_supply") as query:
        with pytest.raises(HTTPException) as error:
            module.get_token_supply(PATH)
    assert error.value.status_code == 404
    query.assert_not_called()


def test_rpc_error_is_explicitly_unavailable_and_not_cached():
    with patch.object(module.database, "fetch_token_candidates", return_value=directory_result()), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value=None), \
         patch.object(module, "query_total_supply", side_effect=TimeoutError) as query:
        first = module.get_token_supply(PATH)
        second = module.get_token_supply(PATH)
    assert not first.available and first.raw_total_supply is None and first.total_supply is None
    assert not second.available and query.call_count == 2


def test_success_cache_hit_avoids_rpc_and_cache_is_chain_path_scoped():
    with patch.object(module.database, "fetch_token_candidates", return_value=directory_result()), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value="https://rpc.example"), \
         patch.object(module, "query_total_supply", return_value="0") as query:
        assert module.get_token_supply(PATH).total_supply == "0"
        assert module.get_token_supply(PATH).total_supply == "0"
        module.app.state.api_config.chain_id = "dev-1"
        assert module.get_token_supply(PATH).total_supply == "0"
    assert query.call_count == 2


@pytest.mark.parametrize(("value", "expected"), [
    ("0", "0"), ("184467440737095516161844674407370955161", "184467440737095516161844674407370955161"),
    ("(42 uint64)", "42"), ("-1", None), ("1.5", None), ("not a number", None), (None, None),
])
def test_rpc_integer_parser_fails_closed(value, expected):
    assert parse_total_supply(value) == expected


def test_decimal_formatting_is_arbitrary_precision_and_trims_zeroes():
    assert decimal_amount("102569491938420", 6) == "102569491.93842"
    assert decimal_amount("300000000000000", 6) == "300000000"
    assert decimal_amount("1", 6) == "0.000001"


def test_cache_is_bounded():
    cache = TokenSupplyCache(ttl_seconds=300, max_entries=1)
    cache.put(("one", PATH), "1")
    cache.put(("two", PATH), "2")
    assert cache.get(("one", PATH)) is None
    assert cache.get(("two", PATH)) == "2"


def test_backend_constructs_only_fixed_qeval_expression():
    client = SimpleNamespace()
    client.abci_query = lambda rpc_path, expression: (rpc_path, expression)
    client.__enter__ = lambda: client
    client.__exit__ = lambda *args: None
    with patch("api.token_supply.GnoRpcClient") as client_type:
        client_type.return_value.__enter__.return_value.abci_query.return_value = "7"
        from api.token_supply import query_total_supply
        assert query_total_supply(rpc_url="https://rpc.example", path=PATH) == "7"
        client_type.return_value.__enter__.return_value.abci_query.assert_called_once_with(
            "vm/qeval", f"{PATH}.TotalSupply()",
        )
