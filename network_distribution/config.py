"""Environment configuration for network-distribution collection."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Config:
    database_url: str
    chain_id: str
    rpc_limit: int
    rpc_health_max_age: int
    geo_api_url: str
    geo_timeout: int
    geo_cache_ttl: int
    geo_failure_ttl: int
    geo_max_lookups: int
    geo_concurrency: int
    snapshot_retention: int

    @classmethod
    def from_env(cls, rpc_limit: int | None = None) -> "Config":
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        chain_id = (os.getenv("NETWORK_DISTRIBUTION_CHAIN_ID") or os.getenv("GNO_CHAIN_ID") or "").strip()
        if not chain_id:
            raise ValueError("NETWORK_DISTRIBUTION_CHAIN_ID or GNO_CHAIN_ID is required")
        configured_limit = _integer("NETWORK_DISTRIBUTION_RPC_LIMIT", 1, 1, 20)
        if rpc_limit is not None and not 1 <= rpc_limit <= 20:
            raise ValueError("--rpc-limit must be between 1 and 20")
        return cls(
            database_url, chain_id, rpc_limit or configured_limit,
            _integer("NETWORK_DISTRIBUTION_RPC_HEALTH_MAX_AGE", 600, 1, 86400),
            os.getenv("NETWORK_DISTRIBUTION_GEO_API_URL", "https://ipwho.is").rstrip("/"),
            _integer("NETWORK_DISTRIBUTION_GEO_TIMEOUT", 10, 1, 120),
            _integer("NETWORK_DISTRIBUTION_GEO_CACHE_TTL", 604800, 3600, 31536000),
            _integer("NETWORK_DISTRIBUTION_GEO_FAILURE_TTL", 3600, 1, 86400),
            _integer("NETWORK_DISTRIBUTION_GEO_MAX_LOOKUPS", 250, 1, 10000),
            _integer("NETWORK_DISTRIBUTION_GEO_CONCURRENCY", 5, 1, 20),
            _integer("NETWORK_DISTRIBUTION_SNAPSHOT_RETENTION", 120, 1, 10000),
        )
