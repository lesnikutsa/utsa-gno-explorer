from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import api.app as module
from api.token_supply import (TokenSupplyCache, decimal_amount, parse_total_supply,
                              parse_native_bank_supply, query_native_gnot_supply,
                              token_supply_cache)


PATH = "gno.land/r/demo/token"


def exact_result(path=PATH, source='grc20.NewToken("Demo", "DMT", 6, 0, cur)'):
    return {
        "candidate": {"path": path},
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
    with patch.object(module.database, "fetch_verified_token_candidate", return_value=result or exact_result()), \
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
    with patch.object(module.database, "fetch_verified_token_candidate", return_value=None) as verify, \
         patch.object(module, "query_total_supply") as query:
        with pytest.raises(HTTPException) as error:
            module.get_token_supply("gno.land/r/demo/not_a_token")
    assert error.value.status_code == 404
    verify.assert_called_once_with(chain_id="sapphire-1", path="gno.land/r/demo/not_a_token")
    query.assert_not_called()

    with patch.object(module.database, "fetch_verified_token_candidate",
                      return_value=exact_result(source="func TotalSupply() uint64 { return 9 }")), \
         patch.object(module, "query_total_supply") as query:
        with pytest.raises(HTTPException) as error:
            module.get_token_supply(PATH)
    assert error.value.status_code == 404
    query.assert_not_called()


def test_package_is_rejected_before_database_or_rpc():
    with patch.object(module.database, "fetch_verified_token_candidate") as verify, \
         patch.object(module, "query_total_supply") as query:
        with pytest.raises(HTTPException) as error:
            module.get_token_supply("gno.land/p/demo/token")
    assert error.value.status_code == 422
    verify.assert_not_called()
    query.assert_not_called()


def test_supply_does_not_load_token_directory():
    with patch.object(module.database, "fetch_token_candidates") as directory:
        call()
    directory.assert_not_called()


def test_rpc_error_is_explicitly_unavailable_and_not_cached():
    with patch.object(module.database, "fetch_verified_token_candidate", return_value=exact_result()), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value=None), \
         patch.object(module, "query_total_supply", side_effect=TimeoutError) as query:
        first = module.get_token_supply(PATH)
        second = module.get_token_supply(PATH)
    assert not first.available and first.raw_total_supply is None and first.total_supply is None
    assert not second.available and query.call_count == 2


def test_rpc_error_log_does_not_expose_credential_bearing_url(caplog):
    secret_url = "https://user:VERY_SECRET@example.invalid/rpc?api_key=ALSO_SECRET"
    with patch.object(module.database, "fetch_verified_token_candidate", return_value=exact_result()), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value=secret_url), \
         patch.object(module, "query_total_supply",
                      side_effect=RuntimeError(f"request failed for {secret_url}")):
        response = module.get_token_supply(PATH)
    assert response.available is False
    assert "Token TotalSupply RPC query failed" in caplog.text
    for secret in ("VERY_SECRET", "ALSO_SECRET", secret_url, "request failed for"):
        assert secret not in caplog.text


def test_success_cache_hit_avoids_rpc_and_cache_is_chain_path_scoped():
    with patch.object(module.database, "fetch_verified_token_candidate", return_value=exact_result()), \
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


def test_native_supply_uses_only_fixed_bank_path_and_preserves_precision():
    raw = "184467440737095516161844674407370955161"
    with patch("api.token_supply.GnoRpcClient") as client_type:
        client_type.return_value.__enter__.return_value.abci_query.return_value = f'"{raw}"'
        assert query_native_gnot_supply(rpc_url="https://rpc.example") == raw
        client_type.return_value.__enter__.return_value.abci_query.assert_called_once_with(
            "bank/supply/ugnot", "",
        )
    with patch.object(module.database, "fetch_selected_rpc_url", return_value="https://selected.example"), \
         patch.object(module, "query_native_gnot_supply", return_value=raw):
        response = module.get_native_token()
    assert response.raw_total_supply == raw
    assert response.total_supply == "184467440737095516161844674407370.955161"
    assert response.base_denom == "ugnot" and response.decimals == 6


@pytest.mark.parametrize(("value", "expected"), [
    ('"0"', "0"),
    ('"00021000000000000"', "21000000000000"),
    ('"184467440737095516161844674407370955161"',
     "184467440737095516161844674407370955161"),
    ('"-1"', None),
    ("1000", None),
    ('"1.5"', None),
    ("true", None),
    ("false", None),
    ("null", None),
    ("[]", None),
    ("{}", None),
    ('{"supply":"1"}', None),
    ('"1" trailing', None),
    (' "1"', None),
    ('"1', None),
])
def test_native_bank_supply_parser_is_protocol_specific_and_fails_closed(value, expected):
    assert parse_native_bank_supply(value) == expected


def test_native_bank_supply_parser_rejects_oversized_responses():
    assert parse_native_bank_supply(f'"{"1" * 513}"') is None
    assert parse_total_supply('"21000000000000"') is None


def test_native_supply_failure_is_unavailable_safe_and_not_directory_dependent(caplog):
    secret_url = "https://user:SECRET@example.invalid/rpc?key=PRIVATE"
    with patch.object(module.database, "fetch_selected_rpc_url", return_value=secret_url), \
         patch.object(module.database, "fetch_token_candidates") as directory, \
         patch.object(module, "query_native_gnot_supply",
                      side_effect=RuntimeError(f"failed {secret_url}")):
        response = module.get_native_token()
    assert response.available is False and response.total_supply is None
    directory.assert_not_called()
    assert "Native GNOT supply RPC query failed" in caplog.text
    assert "SECRET" not in caplog.text and "PRIVATE" not in caplog.text


def test_native_and_wrapped_gnot_use_distinct_supply_paths():
    wrapped = "gno.land/r/gnoland/wugnot"
    with patch.object(module.database, "fetch_verified_token_candidate",
                      return_value=exact_result(wrapped, 'grc20.NewToken("Wrapped GNOT", "WGNOT", 6, 0, cur)')), \
         patch.object(module.database, "fetch_selected_rpc_url", return_value="https://rpc.example"), \
         patch.object(module, "query_total_supply", return_value="10") as wrapped_query, \
         patch.object(module, "query_native_gnot_supply", return_value="20") as native_query:
        module.get_token_supply(wrapped)
        module.get_native_token()
    wrapped_query.assert_called_once_with(rpc_url="https://rpc.example", path=wrapped)
    native_query.assert_called_once_with(rpc_url="https://rpc.example")
