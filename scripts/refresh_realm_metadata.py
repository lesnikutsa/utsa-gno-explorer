#!/usr/bin/env python3
"""Manually collect one fixed-height Realm/Package metadata snapshot."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.realm_catalog import path_kind
from indexer.realm_metadata_collector import CollectionRequest, collect_path_metadata
from indexer.realm_metadata_persistence import (
    MetadataRefreshState,
    persist_metadata_refresh_state_cursor,
    publish_metadata_snapshot,
)
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_probes

LOCK_ID = 0x524D455441444154
MAX_LIMIT = 10_000
LOGGER = logging.getLogger("realm_metadata_refresh")


@dataclass(frozen=True)
class CatalogSelection:
    observed_height: int
    paths: tuple[tuple[str, str], ...]


def positive_limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_LIMIT}")
    return parsed


def bounded_timeout(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 60:
        raise argparse.ArgumentTypeError("must be between 1 and 60")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--limit", type=positive_limit)
    parser.add_argument("--timeout", type=bounded_timeout, default=10)
    return parser


def select_catalog_paths(cursor, chain_id: str, requested: list[str],
                         limit: int | None) -> CatalogSelection:
    if any(path_kind(path) is None for path in requested):
        raise RuntimeError("invalid_requested_path")
    cursor.execute(
        "SELECT observed_height FROM realm_catalog_state WHERE chain_id=%s", (chain_id,)
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("catalog_state_missing")
    height = row[0]
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise RuntimeError("catalog_height_invalid")
    cursor.execute(
        "SELECT path,path_kind FROM realm_catalog "
        "WHERE chain_id=%s AND rpc_visible=true ORDER BY path", (chain_id,)
    )
    available = tuple((str(path), str(kind)) for path, kind in cursor.fetchall())
    if not available:
        raise RuntimeError("no_rpc_visible_paths")
    if any(path_kind(path) != kind for path, kind in available):
        raise RuntimeError("invalid_catalog_path")
    if requested:
        requested_set = set(requested)
        selected = tuple(item for item in available if item[0] in requested_set)
        if len(selected) != len(requested_set):
            raise RuntimeError("requested_path_not_visible")
    else:
        selected = available
    if limit is not None:
        selected = selected[:limit]
    return CatalogSelection(height, selected)


def _persist_state(connection, state: MetadataRefreshState) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            persist_metadata_refresh_state_cursor(cursor, state)


def _close_probes(probes) -> None:
    closed: set[int] = set()
    for probe in probes:
        client = getattr(probe, "client", None)
        if client is not None and id(client) not in closed:
            closed.add(id(client))
            try:
                client.close()
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_clock = time.monotonic()
    probes = []
    connection = None
    running_state: MetadataRefreshState | None = None
    published = failed = 0
    lock_acquired = False
    try:
        config = load_config()
        db = PostgresDatabase(config.database_url)
        connection = db.connect()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
            lock_acquired = bool(cursor.fetchone()[0])
        connection.commit()
        if not lock_acquired:
            LOGGER.error("chain=%s status=already_running", config.chain_id)
            return 1

        with connection.cursor() as cursor:
            selection = select_catalog_paths(cursor, config.chain_id, args.path, args.limit)
        connection.commit()

        preferred = db.get_selected_rpc_url(config.chain_id)
        urls = ([preferred] if preferred else []) + [url for url in config.rpc_urls if url != preferred]
        probes = probe_rpc_endpoints(
            urls, config.chain_id, config.max_height_lag, timeout=args.timeout
        )
        suitable = suitable_rpc_probes(probes)
        if not suitable:
            raise RuntimeError("no_suitable_rpc")
        candidate = suitable[0]
        if candidate.latest_height is None or candidate.latest_height < selection.observed_height:
            raise RuntimeError("rpc_cannot_serve_catalog_height")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM rpc_endpoints WHERE chain_id=%s AND url=%s",
                (config.chain_id, candidate.url),
            )
            endpoint_row = cursor.fetchone()
        connection.commit()
        endpoint_id = int(endpoint_row[0]) if endpoint_row else None

        run_started = datetime.now(timezone.utc)
        running_state = MetadataRefreshState(
            config.chain_id, selection.observed_height, "running", len(selection.paths),
            0, 0, run_started,
        )
        _persist_state(connection, running_state)
        for path, kind in selection.paths:
            result = collect_path_metadata(
                candidate.client,
                CollectionRequest(config.chain_id, path, kind, selection.observed_height,
                                  endpoint_id),
            )
            if result.snapshot is None:
                failed += 1
                LOGGER.info("path=%s kind=%s status=failed observed_height=%s",
                            path, kind, selection.observed_height)
                continue
            try:
                publish_metadata_snapshot(connection, result.snapshot)
            except Exception:
                failed += 1
                LOGGER.info("path=%s kind=%s status=failed observed_height=%s",
                            path, kind, selection.observed_height)
                continue
            published += 1
            LOGGER.info("path=%s kind=%s status=%s observed_height=%s",
                        path, kind, result.status, selection.observed_height)

        terminal = "complete" if failed == 0 else ("partial" if published else "failed")
        completed = datetime.now(timezone.utc)
        _persist_state(connection, MetadataRefreshState(
            config.chain_id, selection.observed_height, terminal, len(selection.paths),
            published, failed, run_started, completed,
            selection.observed_height if terminal == "complete" else None,
            completed if terminal == "complete" else None,
        ))
        LOGGER.info(
            "chain=%s rpc_host=%s height=%s selected=%s published=%s failed=%s "
            "status=%s elapsed=%.3f",
            config.chain_id, urlsplit(candidate.url).hostname or "unknown-host",
            selection.observed_height, len(selection.paths), published, failed,
            terminal, time.monotonic() - started_clock,
        )
        return 0 if terminal == "complete" else 2
    except Exception as exc:
        if running_state is not None and connection is not None:
            try:
                _persist_state(connection, MetadataRefreshState(
                    running_state.chain_id, running_state.observed_height, "failed",
                    running_state.selected_path_count, published, failed,
                    running_state.started_at, datetime.now(timezone.utc),
                ))
            except Exception:
                pass
        LOGGER.error("chain=%s status=%s elapsed=%.3f",
                     getattr(locals().get("config"), "chain_id", "unknown"),
                     type(exc).__name__[:40], time.monotonic() - started_clock)
        return 1
    finally:
        _close_probes(probes)
        if connection is not None:
            if lock_acquired:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
                    connection.commit()
                except Exception:
                    pass
            connection.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
