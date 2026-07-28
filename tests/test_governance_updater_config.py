import os
from unittest.mock import patch

import pytest

from indexer.config import load_governance_updater_config
from indexer.governance_updater import (FatalGovernanceUpdaterError,
                                        GovernanceUpdaterConfig, validate_config)


BASE = {"DATABASE_URL": "postgresql://example/test", "GNO_CHAIN_ID": "topaz-1",
        "GNO_RPC_URLS": "https://rpc", "RPC_MAX_HEIGHT_LAG": "10"}


def load(**values):
    with patch.dict(os.environ, {**BASE, **values}, clear=True):
        return load_governance_updater_config()


def test_safe_defaults_and_environment_overrides():
    value = load()
    assert (value.refresh_interval_seconds, value.full_reconcile_interval_seconds,
            value.error_backoff_seconds, value.max_backoff_seconds) == (30, 21600, 5, 60)
    value = load(GOVERNANCE_REFRESH_INTERVAL_SECONDS="12",
                 GOVERNANCE_FULL_RECONCILE_INTERVAL_SECONDS="120",
                 GOVERNANCE_ERROR_BACKOFF_SECONDS="3", GOVERNANCE_MAX_BACKOFF_SECONDS="30",
                 GNO_GOVERNANCE_REALM="gno.land/r/custom")
    assert (value.refresh_interval_seconds, value.full_reconcile_interval_seconds,
            value.error_backoff_seconds, value.max_backoff_seconds, value.realm) == (12, 120, 3, 30, "gno.land/r/custom")


@pytest.mark.parametrize("name", ["GOVERNANCE_REFRESH_INTERVAL_SECONDS",
    "GOVERNANCE_FULL_RECONCILE_INTERVAL_SECONDS", "GOVERNANCE_ERROR_BACKOFF_SECONDS",
    "GOVERNANCE_MAX_BACKOFF_SECONDS"])
@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_invalid_interval_values_are_rejected(name, value):
    with pytest.raises((ValueError, FatalGovernanceUpdaterError)):
        load(**{name: value})


def test_interval_relationships_are_rejected():
    with pytest.raises(FatalGovernanceUpdaterError):
        load(GOVERNANCE_REFRESH_INTERVAL_SECONDS="31", GOVERNANCE_FULL_RECONCILE_INTERVAL_SECONDS="30")
    with pytest.raises(FatalGovernanceUpdaterError):
        load(GOVERNANCE_ERROR_BACKOFF_SECONDS="61", GOVERNANCE_MAX_BACKOFF_SECONDS="60")


def test_database_and_realm_validation():
    with patch.dict(os.environ, {**BASE, "DATABASE_URL": ""}, clear=True), pytest.raises(FatalGovernanceUpdaterError):
        load_governance_updater_config()
    for realm in ("bad", "gno.land/r/a:b"):
        with pytest.raises(FatalGovernanceUpdaterError): load(GNO_GOVERNANCE_REALM=realm)
    validate_config(GovernanceUpdaterConfig("db", ["rpc"], "topaz-1", "gno.land/r/valid", 10))
