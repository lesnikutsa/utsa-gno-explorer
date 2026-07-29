"""Configuration helpers for the read-only API."""

from dataclasses import dataclass
import os
import unicodedata


DEFAULT_API_VERSION = "0.8.0"
DEFAULT_INDEXER_LAG_DEGRADED_THRESHOLD = 10
DEFAULT_RPC_CHECK_STALE_SECONDS = 60
DEFAULT_GOVERNANCE_REALM = "gno.land/r/gov/dao"
DEFAULT_CHAIN_ID = "topaz-1"
DEFAULT_RPC_MAX_HEIGHT_LAG = 10
DEFAULT_ACCOUNT_RPC_TIMEOUT_SECONDS = 10


class ConfigError(RuntimeError):
    """Raised when required API configuration is missing or invalid."""


@dataclass(frozen=True)
class ApiConfig:
    database_url: str
    api_version: str = DEFAULT_API_VERSION
    indexer_lag_degraded_threshold: int = DEFAULT_INDEXER_LAG_DEGRADED_THRESHOLD
    rpc_check_stale_seconds: int = DEFAULT_RPC_CHECK_STALE_SECONDS
    governance_realm: str = DEFAULT_GOVERNANCE_REALM
    rpc_urls: tuple[str, ...] = ()
    chain_id: str = DEFAULT_CHAIN_ID
    rpc_max_height_lag: int = DEFAULT_RPC_MAX_HEIGHT_LAG
    account_rpc_timeout_seconds: int = DEFAULT_ACCOUNT_RPC_TIMEOUT_SECONDS


def _read_governance_realm() -> str:
    value = os.environ.get("GNO_GOVERNANCE_REALM", DEFAULT_GOVERNANCE_REALM)
    if not isinstance(value, str):
        raise ConfigError("GNO_GOVERNANCE_REALM must be a string")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in value):
        raise ConfigError("GNO_GOVERNANCE_REALM is invalid")
    value = value.strip()
    if (
        not value
        or len(value) > 512
        or not value.startswith("gno.land/r/")
        or ":" in value
        or any(
            character.isspace()
            or not character.isprintable()
            or unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
            for character in value
        )
    ):
        raise ConfigError("GNO_GOVERNANCE_REALM is invalid")
    return value


def _read_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < 0:
        raise ConfigError(f"{name} must be greater than or equal to 0")
    return value


def _read_rpc_urls() -> tuple[str, ...]:
    if "GNO_RPC_URLS" in os.environ:
        return tuple(item.strip() for item in os.environ["GNO_RPC_URLS"].split(",") if item.strip())
    legacy = os.environ.get("GNO_RPC_URL", "").strip()
    return (legacy,) if legacy else ()


def _read_chain_id() -> str:
    value = os.environ.get("GNO_CHAIN_ID", DEFAULT_CHAIN_ID)
    if not value or len(value) > 128 or value != value.strip() or not value.isprintable():
        raise ConfigError("GNO_CHAIN_ID is invalid")
    return value


def _read_account_timeout() -> int:
    value = _read_int("API_ACCOUNT_RPC_TIMEOUT_SECONDS", DEFAULT_ACCOUNT_RPC_TIMEOUT_SECONDS)
    if not 1 <= value <= 30:
        raise ConfigError("API_ACCOUNT_RPC_TIMEOUT_SECONDS must be between 1 and 30")
    return value


def load_config() -> ApiConfig:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ConfigError("DATABASE_URL is required")
    return ApiConfig(
        database_url=database_url,
        api_version=os.environ.get("API_VERSION") or DEFAULT_API_VERSION,
        indexer_lag_degraded_threshold=_read_int(
            "API_INDEXER_LAG_DEGRADED_THRESHOLD",
            DEFAULT_INDEXER_LAG_DEGRADED_THRESHOLD,
        ),
        rpc_check_stale_seconds=_read_int(
            "API_RPC_CHECK_STALE_SECONDS",
            DEFAULT_RPC_CHECK_STALE_SECONDS,
        ),
        governance_realm=_read_governance_realm(),
        rpc_urls=_read_rpc_urls(),
        chain_id=_read_chain_id(),
        rpc_max_height_lag=_read_int("RPC_MAX_HEIGHT_LAG", DEFAULT_RPC_MAX_HEIGHT_LAG),
        account_rpc_timeout_seconds=_read_account_timeout(),
    )
