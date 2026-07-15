"""Configuration helpers for the bounded indexer."""
from __future__ import annotations

import os
from dataclasses import dataclass

from scripts.inspect_rpc import configured_chain_id, configured_max_height_lag, configured_rpc_urls, load_dotenv

DEFAULT_MAX_HEIGHTS = 10
DEFAULT_HARD_MAX_HEIGHTS = 100
DEFAULT_INDEXER_BATCH_SIZE = 10
DEFAULT_INDEXER_POLL_INTERVAL_SECONDS = 5
DEFAULT_INDEXER_ERROR_BACKOFF_SECONDS = 5
DEFAULT_INDEXER_MAX_BACKOFF_SECONDS = 60


@dataclass(frozen=True)
class IndexerConfig:
    database_url: str
    rpc_urls: list[str]
    chain_id: str
    max_height_lag: int
    hard_max_heights: int


def configured_hard_max_heights() -> int:
    load_dotenv()
    raw_value = os.environ.get("INDEXER_HARD_MAX_HEIGHTS", str(DEFAULT_HARD_MAX_HEIGHTS)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("INDEXER_HARD_MAX_HEIGHTS must be an integer") from exc
    if value < 1:
        raise ValueError("INDEXER_HARD_MAX_HEIGHTS must be positive")
    return value


def load_config() -> IndexerConfig:
    load_dotenv()
    return IndexerConfig(
        database_url=os.environ.get("DATABASE_URL", "").strip(),
        rpc_urls=configured_rpc_urls(),
        chain_id=configured_chain_id(),
        max_height_lag=configured_max_height_lag(),
        hard_max_heights=configured_hard_max_heights(),
    )


def _optional_positive_int(name: str) -> int | None:
    load_dotenv()
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_int(name: str, default: int) -> int:
    value = _optional_positive_int(name)
    return default if value is None else value


def load_continuous_config():
    from .runner import ContinuousConfig

    return ContinuousConfig(
        start_height=_optional_positive_int("INDEXER_START_HEIGHT"),
        batch_size=_positive_int("INDEXER_BATCH_SIZE", DEFAULT_INDEXER_BATCH_SIZE),
        poll_interval_seconds=_positive_int("INDEXER_POLL_INTERVAL_SECONDS", DEFAULT_INDEXER_POLL_INTERVAL_SECONDS),
        error_backoff_seconds=_positive_int("INDEXER_ERROR_BACKOFF_SECONDS", DEFAULT_INDEXER_ERROR_BACKOFF_SECONDS),
        max_backoff_seconds=_positive_int("INDEXER_MAX_BACKOFF_SECONDS", DEFAULT_INDEXER_MAX_BACKOFF_SECONDS),
    )
