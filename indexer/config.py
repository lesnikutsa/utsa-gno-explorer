"""Configuration helpers for the bounded indexer."""
from __future__ import annotations

import os
from dataclasses import dataclass

from scripts.inspect_rpc import configured_chain_id, configured_max_height_lag, configured_rpc_urls, load_dotenv

DEFAULT_MAX_HEIGHTS = 10
DEFAULT_HARD_MAX_HEIGHTS = 100


@dataclass(frozen=True)
class IndexerConfig:
    database_url: str
    rpc_urls: list[str]
    chain_id: str
    max_height_lag: int
    hard_max_heights: int


def configured_hard_max_heights() -> int:
    load_dotenv()
    raw = os.environ.get("INDEXER_HARD_MAX_HEIGHTS", str(DEFAULT_HARD_MAX_HEIGHTS)).strip()
    try:
        value = int(raw)
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
