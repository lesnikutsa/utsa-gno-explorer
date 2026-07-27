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
