#!/usr/bin/env python3
"""Inspect Realm activity coverage without modifying PostgreSQL."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase, RealmActivityCoverageError


def _print(values):
    print(" ".join(f"{key}={value}" for key, value in values.items()))


def run() -> int:
    try:
        config = load_config()
        database = PostgresDatabase(config.database_url)
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT activity_from_height, activity_through_height FROM realm_catalog_state WHERE chain_id = %s", (config.chain_id,))
            coverage = cursor.fetchone()
            cursor.execute("SELECT chain_id, last_finalized_height FROM indexer_state WHERE state_key = 'default'")
            indexed = cursor.fetchone()
            if coverage is None or indexed is None or indexed[0] != config.chain_id:
                raise RealmActivityCoverageError("Realm or indexer state is missing or belongs to another chain")
            start, through = coverage
            if start is None or through is None:
                raise RealmActivityCoverageError("Realm activity coverage is not initialized")
            indexed_height = int(indexed[1])
            if int(through) > indexed_height:
                raise RealmActivityCoverageError("Realm activity coverage is ahead of the indexer checkpoint")
            values = {"chain_id": config.chain_id, "activity_from_height": start,
                      "activity_through_height": through, "indexed_height": indexed_height}
            if int(through) == indexed_height:
                values["status"] = "aligned"
            else:
                values.update({"recommended_from_height": start,
                               "recommended_through_height": indexed_height,
                               "status": "rebuild_required"})
            _print(values)
            return 0
    except Exception as exc:
        print(f"status=error error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
