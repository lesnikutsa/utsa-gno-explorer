#!/usr/bin/env python3
"""Inspect Realm call index coverage without modifying PostgreSQL."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase


def run(database_url: str | None = None) -> int:
    """Print bounded coverage facts and return a stable health exit code."""
    try:
        config = load_config()
        database = PostgresDatabase(database_url or config.database_url)
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT from_height, through_height FROM realm_call_index_state "
                "WHERE chain_id = %s",
                (config.chain_id,),
            )
            state = cursor.fetchone()
            cursor.execute(
                "SELECT last_finalized_height FROM indexer_state "
                "WHERE state_key = 'default' AND chain_id = %s",
                (config.chain_id,),
            )
            indexed = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM realm_call_index WHERE chain_id = %s",
                (config.chain_id,),
            )
            row_count = int(cursor.fetchone()[0])

        indexed_height = int(indexed[0]) if indexed else None
        if state is None:
            print(
                f"chain_id={config.chain_id} call_index_from=missing "
                f"call_index_through=missing "
                f"indexed_height={indexed_height if indexed_height is not None else 'missing'} "
                f"row_count={row_count} contiguous=false rebuild_required=true"
            )
            return 2

        start, through = int(state[0]), int(state[1])
        contiguous = indexed_height is not None and through == indexed_height
        print(
            f"chain_id={config.chain_id} call_index_from={start} "
            f"call_index_through={through} "
            f"indexed_height={indexed_height if indexed_height is not None else 'missing'} "
            f"row_count={row_count} contiguous={str(contiguous).lower()} "
            f"rebuild_required={str(not contiguous).lower()}"
        )
        return 0 if contiguous else 3
    except Exception as exc:
        print(f"status=error error={type(exc).__name__}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    args = parser.parse_args()
    raise SystemExit(run(args.database_url))
