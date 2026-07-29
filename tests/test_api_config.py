import os
from unittest.mock import patch

import pytest

from api.config import ConfigError, DEFAULT_GOVERNANCE_REALM, load_config


def load(**environment):
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example/test", **environment}, clear=True):
        return load_config()


def test_governance_realm_default_and_environment():
    assert load().governance_realm == DEFAULT_GOVERNANCE_REALM
    assert load(GNO_GOVERNANCE_REALM="  gno.land/r/gov/custom  ").governance_realm == "gno.land/r/gov/custom"
    assert load(GNO_GOVERNANCE_REALM="gno.land/r/gov/dao/nested").governance_realm == "gno.land/r/gov/dao/nested"


@pytest.mark.parametrize("value", [
    "", "x" * 513, "example/r/gov", "gno.land/r/a:b", "gno.land/r/a\n",
    "gno.land/r/a\tb", "gno.land/r/a b", "gno.land/r/a\u00a0b", "gno.land/r/a\u2028b",
])
def test_invalid_governance_realm_is_rejected(value):
    with pytest.raises(ConfigError):
        load(GNO_GOVERNANCE_REALM=value)


def test_database_url_remains_required():
    with patch.dict(os.environ, {}, clear=True), pytest.raises(ConfigError):
        load_config()


def test_account_rpc_configuration():
    config = load(GNO_RPC_URLS=" https://one.example, ,https://two.example ", GNO_RPC_URL="https://legacy.example",
                  GNO_CHAIN_ID="topaz-test", RPC_MAX_HEIGHT_LAG="12", API_ACCOUNT_RPC_TIMEOUT_SECONDS="7")
    assert config.rpc_urls == ("https://one.example", "https://two.example")
    assert config.chain_id == "topaz-test"
    assert config.rpc_max_height_lag == 12
    assert config.account_rpc_timeout_seconds == 7


def test_legacy_and_missing_rpc_configuration():
    assert load(GNO_RPC_URL="https://legacy.example").rpc_urls == ("https://legacy.example",)
    assert load().rpc_urls == ()


@pytest.mark.parametrize("environment", [
    {"RPC_MAX_HEIGHT_LAG": "-1"}, {"RPC_MAX_HEIGHT_LAG": "bad"},
    {"API_ACCOUNT_RPC_TIMEOUT_SECONDS": "0"}, {"API_ACCOUNT_RPC_TIMEOUT_SECONDS": "31"},
    {"GNO_CHAIN_ID": ""}, {"GNO_CHAIN_ID": " bad"}, {"GNO_CHAIN_ID": "bad\nchain"},
])
def test_invalid_account_rpc_configuration(environment):
    with pytest.raises(ConfigError):
        load(**environment)
