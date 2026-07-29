import json
import threading
import time
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import pytest

from api.account_adapters import AccountParseError, parse_auth_account, parse_bank_balances, parse_coins
from api.account_service import AccountUnavailableError, fetch_live_account, public_rpc_url
from api import account_service
from api.config import ApiConfig
from api.database import ApiDatabase
from api.network_profile import BECH32_CHARSET, _convert_bits, _expand_hrp, _polymod, topaz_profile, validate_account_address
from indexer.rpc import RpcProbeResult


UTSA = "g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75"
PROFILE = topaz_profile("topaz-1")


@pytest.fixture(autouse=True)
def clear_account_probe_cache():
    with account_service._probe_cache_lock:
        account_service._probe_cache.clear()


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


@pytest.mark.parametrize("text,expected", [
    ('"17569800ugnot"', [("ugnot", "17569800", "17.5698")]),
    ('""', []),
    ('"2foo,1ugnot"', [("foo", "2", "2"), ("ugnot", "1", "0.000001")]),
])
def test_bank_response_decodes_json_coins_string(text, expected):
    balances = parse_bank_balances(text, PROFILE)
    assert [(item["denom"], item["amount"], item["display_amount"]) for item in balances] == expected


@pytest.mark.parametrize("text", [
    "17569800ugnot", "null", "{}", "[]", "1", "true", '"unterminated',
    '"1ugnot,2ugnot"', '"-1ugnot"',
])
def test_bank_response_rejects_non_string_or_malformed_values(text):
    with pytest.raises(AccountParseError):
        parse_bank_balances(text, PROFILE)


def test_bank_response_rejects_oversized_json_string():
    with pytest.raises(AccountParseError):
        parse_bank_balances('"' + ("1" * 262144) + '"', PROFILE)


class Client:
    base_url = "https://fresh.example/"
    def __init__(self, values, base_url=None):
        self.values = iter(values)
        self.calls = []
        self.lock = threading.Lock()
        if base_url is not None:
            self.base_url = base_url
    def abci_query(self, path, data, height=None):
        with self.lock:
            self.calls.append((path, data, height))
            return next(self.values)


class Candidate:
    latest_height = 100
    finalized_tip = 99
    def __init__(self, values): self.client = Client(values)


def test_service_failover_and_confirmed_missing():
    config = ApiConfig("postgres://test", rpc_urls=("a", "b"))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates",
        return_value=[Candidate(["bad", '""']), Candidate(["null", '""'])],
    ):
        result = fetch_live_account(UTSA, config)
    assert result["found"] is False
    assert result["observed_height"] == 99


def test_service_uses_path_queries_with_empty_data():
    candidate = Candidate([auth(), '"1ugnot"'])
    config = ApiConfig("postgres://test", rpc_urls=("a",))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates", return_value=[candidate],
    ):
        fetch_live_account(UTSA, config)
    assert candidate.client.calls == [
        (f"auth/accounts/{UTSA}", "", 99),
        (f"bank/balances/{UTSA}", "", 99),
    ]


@pytest.mark.parametrize("raw,expected", [
    ("https://user:pass@rpc.example:443/path?token=secret#x", "https://rpc.example:443/path"),
    ("https://rpc.example/?apikey=secret", "https://rpc.example/"),
])
def test_public_rpc_url_removes_private_components(raw, expected):
    result = public_rpc_url(raw)
    assert result == expected
    assert "user" not in result and "pass" not in result
    assert "token" not in result and "apikey" not in result and "#" not in result


def test_malformed_public_rpc_url_triggers_failover():
    bad, good = Candidate([auth(), '""']), Candidate([auth(), '""'])
    bad.client.base_url = "not a URL?token=secret"
    config = ApiConfig("postgres://test", rpc_urls=("a", "b"))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates", return_value=[bad, good],
    ):
        result = fetch_live_account(UTSA, config)
    assert result["source"]["rpc_url"] == "https://fresh.example/"


def test_service_all_candidates_failed_is_safe():
    config = ApiConfig("postgres://test", rpc_urls=("a",))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[]), patch("api.account_service.suitable_rpc_candidates", return_value=[]):
        with pytest.raises(AccountUnavailableError):
            fetch_live_account(UTSA, config)


def test_missing_auth_with_nonempty_bank_fails_over_to_valid_candidate():
    inconsistent = Candidate(["null", '"1ugnot"'])
    valid = Candidate([auth(), '"1ugnot"'])
    config = ApiConfig("postgres://test", rpc_urls=("a", "b"))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates", return_value=[inconsistent, valid],
    ):
        result = fetch_live_account(UTSA, config)
    assert result["found"] is True
    assert result["balances"][0]["amount"] == "1"


def test_malformed_bank_candidate_fails_over_to_valid_candidate():
    malformed = Candidate([auth(), "1ugnot"])
    valid = Candidate([auth(), '"1ugnot"'])
    config = ApiConfig("postgres://test", rpc_urls=("a", "b"))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[object()]), patch(
        "api.account_service.suitable_rpc_candidates", return_value=[malformed, valid],
    ):
        result = fetch_live_account(UTSA, config)
    assert result["source"]["rpc_url"] == "https://fresh.example/"
    assert result["balances"][0]["display_amount"] == "0.000001"


def cacheable_probe(url="https://rpc.example"):
    client = Client([], base_url=url)
    return RpcProbeResult(
        url=url, healthy=True, selected=True, latest_height=100, observed_lag=0,
        client=client, status_payload={"result": {}}, response_seconds=0.1,
    )


def test_account_probe_cache_hit_expiry_key_and_copy_safety():
    first = cacheable_probe()
    config = ApiConfig("postgres://test", rpc_urls=("https://rpc.example",))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[first]) as probe:
        one, hit_one, _ = account_service._account_probes(config)
        one.clear()
        two, hit_two, _ = account_service._account_probes(config)
        different, hit_different, _ = account_service._account_probes(
            ApiConfig("postgres://test", rpc_urls=("https://other.example",)),
        )
    assert not hit_one and hit_two and not hit_different
    assert two == [first] and different == [first]
    assert probe.call_count == 2

    with patch.object(account_service, "ACCOUNT_RPC_PROBE_CACHE_TTL_SECONDS", 0), patch(
        "api.account_service.probe_rpc_endpoints", return_value=[first],
    ) as expired_probe:
        _, expired_hit, _ = account_service._account_probes(config)
    assert not expired_hit and expired_probe.call_count == 1


def test_all_failed_probe_is_not_cached_and_concurrent_cache_access_is_safe():
    failed = RpcProbeResult("https://down.example", False, False)
    config = ApiConfig("postgres://test", rpc_urls=("https://down.example",))
    with patch("api.account_service.probe_rpc_endpoints", return_value=[failed]) as probe:
        account_service._account_probes(config)
        account_service._account_probes(config)
    assert probe.call_count == 2

    healthy = cacheable_probe()
    with patch("api.account_service.probe_rpc_endpoints", return_value=[healthy]) as probe:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: account_service._account_probes(config), range(8)))
    assert probe.call_count == 1
    assert sum(hit for _, hit, _ in results) == 7


def test_account_queries_run_in_parallel_at_finalized_height(caplog):
    class ParallelClient:
        base_url = "https://user:secret@rpc.example/path?token=hidden"

        def __init__(self):
            self.calls = []

        def abci_query(self, path, data, height=None):
            self.calls.append((path, height))
            time.sleep(0.12)
            return auth() if path.startswith("auth/") else '"1ugnot"'

    client = ParallelClient()
    candidate = Candidate([])
    candidate.client = client
    config = ApiConfig("postgres://test", rpc_urls=("a",))
    started_at = time.perf_counter()
    with patch("api.account_service._account_probes", return_value=([cacheable_probe()], True, None)), patch(
        "api.account_service.suitable_rpc_candidates", return_value=[candidate],
    ), caplog.at_level("INFO"):
        result = fetch_live_account(UTSA, config)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.21
    assert {height for _, height in client.calls} == {99}
    assert result["observed_height"] == 99
    assert "selected_rpc_hostname=rpc.example" in caplog.text
    assert "auth_query_seconds=" in caplog.text and "bank_query_seconds=" in caplog.text
    assert "secret" not in caplog.text and "hidden" not in caplog.text


class FakeDatabase:
    def __init__(self, relation=None, error=None):
        self.relation = relation or {"moniker": "UTSA", "operator_address": UTSA, "signing_address": "A"}
        self.error = error
        self.relation_calls = []
    def open(self, config): pass
    def close(self): pass
    def fetch_account_validator_relation(self, value):
        self.relation_calls.append(value)
        if self.error:
            raise self.error
        return {**self.relation, "operator_address": value}


def test_endpoint_found_contract_and_invalid_short_circuit():
    from api import app as module
    config = ApiConfig("postgres://test")
    live = {"address": UTSA, "found": True, "balances": parse_coins("1ugnot", PROFILE),
            "account_number": "275", "sequence": "1", "public_key": None,
            "source": {"kind": "rpc", "chain_id": "topaz-1", "rpc_url": "https://rpc.example"}, "observed_height": 100}
    module.app.state.api_config = config
    fake_database = FakeDatabase()
    with patch.object(module, "database", fake_database), patch.object(module, "fetch_live_account", return_value=live) as fetch:
        response = module.get_account(UTSA)
        with pytest.raises(module.HTTPException) as invalid:
            module.get_account("not-an-address")
    assert response.model_dump()["validator_relation"]["moniker"] == "UTSA"
    assert invalid.value.status_code == 422 and invalid.value.detail == "Invalid account address"
    assert fetch.call_count == 1
    assert fake_database.relation_calls == [UTSA]


def test_endpoint_missing_account_does_not_query_database():
    from api import app as module
    module.app.state.api_config = ApiConfig("postgres://test")
    live = {"address": UTSA, "found": False, "balances": [], "account_number": None,
            "sequence": None, "public_key": None, "source": {"kind": "rpc", "chain_id": "topaz-1",
            "rpc_url": "https://rpc.example"}, "observed_height": 100}
    fake_database = FakeDatabase(error=AssertionError("DB must not be called"))
    with patch.object(module, "database", fake_database), patch.object(module, "fetch_live_account", return_value=live):
        response = module.get_account(UTSA)
    assert response.validator_relation is None
    assert fake_database.relation_calls == []


def test_endpoint_safe_503_does_not_leak():
    from api import app as module
    module.app.state.api_config = ApiConfig("postgres://secret")
    with patch.object(module, "database", FakeDatabase()), patch.object(module, "fetch_live_account", side_effect=AccountUnavailableError("secret")):
        with pytest.raises(module.HTTPException) as response:
            module.get_account(UTSA)
    assert response.value.status_code == 503
    assert response.value.detail == "Account data is temporarily unavailable"


@pytest.mark.parametrize("error", [RuntimeError("duplicate"), OSError("database secret")])
def test_endpoint_database_failure_is_safe(error):
    from api import app as module
    module.app.state.api_config = ApiConfig("postgres://secret")
    live = {"address": UTSA, "found": True, "balances": [], "account_number": "1", "sequence": "0",
            "public_key": None, "source": {"kind": "rpc", "chain_id": "topaz-1",
            "rpc_url": "https://rpc.example"}, "observed_height": 100}
    with patch.object(module, "database", FakeDatabase(error=error)), patch.object(module, "fetch_live_account", return_value=live):
        with pytest.raises(module.HTTPException) as response:
            module.get_account(UTSA)
    assert response.value.status_code == 503
    assert response.value.detail == "Account data is temporarily unavailable"


class FakeCursor:
    def __init__(self, rows): self.rows, self.parameters = rows, None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, parameters): self.sql, self.parameters = sql, parameters
    def fetchall(self): return self.rows


class FakeConnection:
    def __init__(self, cursor): self._cursor = cursor
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self._cursor


class FakePool:
    def __init__(self, rows): self.cursor = FakeCursor(rows)
    def connection(self, timeout): return FakeConnection(self.cursor)


@pytest.mark.parametrize("rows,expected", [
    ([], None),
    ([{"moniker": "UTSA", "operator_address": UTSA, "signing_address": "SIGN"}],
     {"moniker": "UTSA", "operator_address": UTSA, "signing_address": "SIGN"}),
])
def test_validator_relation_zero_or_one_exact_operator_row(rows, expected):
    database = ApiDatabase()
    database.pool = FakePool(rows)
    assert database.fetch_account_validator_relation(UTSA) == expected
    assert database.pool.cursor.parameters == (UTSA,)
    assert "operator_address = %s" in database.pool.cursor.sql
    assert "signing_address = %s" not in database.pool.cursor.sql


def test_validator_relation_duplicate_rows_are_rejected():
    database = ApiDatabase()
    database.pool = FakePool([{"operator_address": UTSA}, {"operator_address": UTSA}])
    with pytest.raises(RuntimeError):
        database.fetch_account_validator_relation(UTSA)
