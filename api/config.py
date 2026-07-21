"""Configuration helpers for the read-only API."""

from dataclasses import dataclass
import os


DEFAULT_API_VERSION = "0.8.0"
DEFAULT_INDEXER_LAG_DEGRADED_THRESHOLD = 10
DEFAULT_RPC_CHECK_STALE_SECONDS = 60


class ConfigError(RuntimeError):
    """Raised when required API configuration is missing or invalid."""


@dataclass(frozen=True)
class ApiConfig:
    database_url: str
    api_version: str = DEFAULT_API_VERSION
    indexer_lag_degraded_threshold: int = DEFAULT_INDEXER_LAG_DEGRADED_THRESHOLD
    rpc_check_stale_seconds: int = DEFAULT_RPC_CHECK_STALE_SECONDS


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
    )
