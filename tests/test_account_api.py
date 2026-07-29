import json
from unittest.mock import patch

import pytest

from api.account_adapters import AccountParseError, parse_auth_account, parse_coins
from api.account_service import AccountUnavailableError, fetch_live_account
from api.config import ApiConfig
from api.network_profile import BECH32_CHARSET, _convert_bits, _expand_hrp, _polymod, topaz_profile, validate_account_address


UTSA = "g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75"
PROFILE = topaz_profile("topaz-1")


def address(payload=b"\x01" * 20, hrp="g"):
    values = list(_convert_bits(list(payload), 8, 5, True))
    polymod = _polymod(_expand_hrp(hrp) + values + [0] * 6) ^ 1
    checksum = [(polymod >> (5 * (5 - index))) & 31 for index in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[value] for value in values + checksum)


def auth(**changes):
    base = {"address": UTSA, "coins": "", "public_key": None, "account_number": "275", "sequence": "1"}
    base.update(changes)
    return json.dumps({"BaseAccount": base, "attributes": "0"})


@pytest.mark.parametrize("value,expected", [
    (UTSA, True), (address(), True), (UTSA[:-1] + "q", False), (address(hrp="x"), False),
    (UTSA.upper(), False), (" " + UTSA, False), (UTSA.replace("m", "i"), False),
    (address(b"x" * 19), False), ("g1" + "q" * 100, False), ("", False),
])
def test_strict_address_validation(value, expected):
    assert validate_account_address(value, PROFILE) is expected


def test_auth_account_and_public_key_parsing():
    result = parse_auth_account(auth(public_key={"@type": "/tm.PubKeySecp256k1", "value": "abc"}), UTSA)
    assert result == {"account_number": "275", "sequence": "1", "public_key": {"type": "/tm.PubKeySecp256k1", "value": "abc"}}
    assert parse_auth_account("null", UTSA) is None
    assert parse_auth_account(auth(public_key=None), UTSA)["public_key"] is None


@pytest.mark.parametrize("value", [auth(address=address()), auth(account_number="-1"), auth(public_key={"@type": "x"}), "{bad"])
def test_malformed_auth_is_rejected(value):
    with pytest.raises(AccountParseError):
        parse_auth_account(value, UTSA)


@pytest.mark.parametrize("coins,expected", [
    ("", []), ("1ugnot", [("ugnot", "0.000001")]), ("1000000ugnot", [("ugnot", "1")]),
    ("17569800ugnot", [("ugnot", "17.5698")]), ("0ugnot", [("ugnot", "0")]),
    ("2foo,1ugnot", [("foo", "2"), ("ugnot", "0.000001")]),
    ("999999999999999999999999999ugnot", [("ugnot", "999999999999999999999.999999")]),
])
def test_coin_parsing_and_exact_display(coins, expected):
    assert [(item["denom"], item["display_amount"]) for item in parse_coins(coins, PROFILE)] == expected


@pytest.mark.parametrize("coins", ["-1ugnot", "1.0ugnot", "1ugnot,2ugnot", "1", "1" + "x" * 129])
def test_malformed_coins_are_rejected(coins):
    with pytest.raises(AccountParseError):
        parse_coins(coins, PROFILE)


class Client:
    base_url = "https://fresh.example/"
    def __init__(self, values): self.values = iter(values)
    def abci_query(self, path, data): return next(self.values)


class Candidate:
    latest_height = 100
    def __init__(self, values): self.client = Client(values)


def test_service_failover_and_confirmed_missing():
    config = ApiConfig("postgres://test", rpc_urls=("a", "b"))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates",
        return_value=[Candidate(["bad", ""]), Candidate(["null", ""])],
    ):
        result = fetch_live_account(UTSA, config)
    assert result["found"] is False
    assert result["observed_height"] == 100


def test_service_all_candidates_failed_is_safe():
    config = ApiConfig("postgres://test", rpc_urls=("a",))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[]), patch("api.account_service.suitable_rpc_candidates", return_value=[]):
        with pytest.raises(AccountUnavailableError):
            fetch_live_account(UTSA, config)


class FakeDatabase:
    def open(self, config): pass
    def close(self): pass
    def fetch_account_validator_relation(self, value):
        return {"moniker": "UTSA", "operator_address": value, "signing_address": "A"}


def test_endpoint_found_contract_and_invalid_short_circuit():
    from api import app as module
    config = ApiConfig("postgres://test")
    live = {"address": UTSA, "found": True, "balances": parse_coins("1ugnot", PROFILE),
            "account_number": "275", "sequence": "1", "public_key": None,
            "source": {"kind": "rpc", "chain_id": "topaz-1", "rpc_url": "https://rpc.example"}, "observed_height": 100}
    module.app.state.api_config = config
    with patch.object(module, "database", FakeDatabase()), patch.object(module, "fetch_live_account", return_value=live) as fetch:
        response = module.get_account(UTSA)
        with pytest.raises(module.HTTPException) as invalid:
            module.get_account("not-an-address")
    assert response.model_dump()["validator_relation"]["moniker"] == "UTSA"
    assert invalid.value.status_code == 422 and invalid.value.detail == "Invalid account address"
    assert fetch.call_count == 1


def test_endpoint_safe_503_does_not_leak():
    from api import app as module
    module.app.state.api_config = ApiConfig("postgres://secret")
    with patch.object(module, "database", FakeDatabase()), patch.object(module, "fetch_live_account", side_effect=AccountUnavailableError("secret")):
        with pytest.raises(module.HTTPException) as response:
            module.get_account(UTSA)
    assert response.value.status_code == 503
    assert response.value.detail == "Account data is temporarily unavailable"
