#!/usr/bin/env python3
"""Inspect or explicitly repair Realm activity coverage metadata."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config
from indexer.database import (PostgresDatabase, RealmActivityCoverageError,
                              advance_realm_activity_coverage)


def _print(values):
    print(" ".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                   for key, value in values.items()))


def run(apply: bool = False) -> int:
    try:
        config = load_config()
        database = PostgresDatabase(config.database_url)
        with database.connect() as connection:
            try:
                with connection.cursor() as cursor:
                    lock = " FOR UPDATE" if apply else ""
                    cursor.execute("SELECT activity_from_height, activity_through_height FROM realm_catalog_state WHERE chain_id = %s" + lock, (config.chain_id,))
                    coverage = cursor.fetchone()
                    cursor.execute("SELECT chain_id, last_finalized_height FROM indexer_state WHERE state_key = 'default'" + lock)
                    indexed = cursor.fetchone()
                    if coverage is None or indexed is None or indexed[0] != config.chain_id:
                        raise RealmActivityCoverageError("Realm or indexer state is missing or belongs to another chain")
                    start, through = coverage
                    if start is None or through is None:
                        raise RealmActivityCoverageError("Realm activity coverage is not initialized")
                    candidate = int(indexed[1])
                    if candidate < int(through):
                        raise RealmActivityCoverageError(
                            "Realm activity coverage is ahead of the indexer checkpoint"
                        )
                    cursor.execute("SELECT count(*) FROM blocks WHERE height >= %s AND height <= %s", (int(through) + 1, candidate))
                    observed = int(cursor.fetchone()[0]) if candidate > int(through) else 0
                    missing = max(0, candidate - int(through) - observed)
                    if not apply:
                        if missing == 0:
                            # Exercise the same locking and continuity validation as
                            # apply, then explicitly discard its prospective update.
                            advance_realm_activity_coverage(cursor, config.chain_id, candidate)
                        connection.rollback()
                        _print({"chain_id": config.chain_id, "activity_from_height": start,
                                "activity_through_height": through, "indexed_height": candidate,
                                "missing_block_count": missing, "candidate_through_height": candidate,
                                "action": "check", "status": "ready" if missing == 0 else "gap"})
                        return 0 if missing == 0 else 1
                    result = advance_realm_activity_coverage(cursor, config.chain_id, candidate)
                connection.commit()
                _print({"previous_through_height": result.previous_through_height,
                        "new_through_height": result.new_through_height,
                        "advanced": result.advanced, "status": "success"})
                return 0
            except Exception:
                connection.rollback()
                raise
    except Exception as exc:
        # Deliberately omit driver text because it can contain SQL or environment data.
        name = type(exc).__name__
        print(f"status=error error={name}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist a verified coverage advance")
    return run(parser.parse_args().apply)


if __name__ == "__main__":
    raise SystemExit(main())
