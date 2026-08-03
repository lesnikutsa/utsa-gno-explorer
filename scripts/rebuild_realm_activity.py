#!/usr/bin/env python3
"""Explicit one-shot rebuild of transaction-derived Realm catalog aggregates."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase, upsert_transaction_catalog_aggregates
from indexer.realm_catalog import aggregate_block

LOCK_ID = 0x5245414C4D524542


class RebuildError(RuntimeError):
    """A bounded rebuild precondition or invariant failed."""


def rebuild_cursor(cursor, chain_id: str, from_height: int,
                   through_height: int, dry_run: bool = False) -> int:
    """Validate, read and optionally replace derived activity; return unique paths."""
    if (not isinstance(from_height, int) or isinstance(from_height, bool)
            or not isinstance(through_height, int) or isinstance(through_height, bool)
            or from_height < 1 or through_height < from_height):
        raise RebuildError("activity range must contain ordered positive heights")

    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
    cursor.execute("SELECT 1 FROM realm_catalog_state WHERE chain_id = %s", (chain_id,))
    if cursor.fetchone() is None:
        raise RebuildError("Realm catalog state is missing; run refresh_realm_catalog.py first")

    cursor.execute(
        "SELECT last_finalized_height FROM indexer_state WHERE state_key = %s AND chain_id = %s",
        ("default", chain_id),
    )
    checkpoint_row = cursor.fetchone()
    if checkpoint_row is None or through_height > int(checkpoint_row[0]):
        raise RebuildError("activity range exceeds the indexed checkpoint")

    cursor.execute(
        """SELECT count(*)::bigint, min(height), max(height)
           FROM blocks WHERE height BETWEEN %s AND %s""",
        (from_height, through_height),
    )
    block_count, minimum_height, maximum_height = cursor.fetchone()
    expected_blocks = through_height - from_height + 1
    if (int(block_count) != expected_blocks or minimum_height != from_height
            or maximum_height != through_height):
        raise RebuildError("activity range contains missing local blocks")

    cursor.execute(
        """SELECT t.block_height, t.tx_index, t.payload_summary,
                  execution.execution_status, block.time_utc
           FROM transactions t
           JOIN blocks block ON block.height = t.block_height
           LEFT JOIN transaction_execution_results execution
             ON execution.block_height = t.block_height
            AND execution.tx_index = t.tx_index
           WHERE t.block_height BETWEEN %s AND %s
           ORDER BY t.block_height, t.tx_index""",
        (from_height, through_height),
    )
    grouped: dict[tuple[int, object], list[tuple[int, object, str | None]]] = {}
    for height, index, summary, status, block_time in cursor.fetchall():
        grouped.setdefault((int(height), block_time), []).append((int(index), summary, status))

    block_aggregates = {
        key: aggregate_block(transactions) for key, transactions in grouped.items()
    }
    unique_paths = {aggregate.path for aggregates in block_aggregates.values()
                    for aggregate in aggregates}
    if dry_run:
        return len(unique_paths)

    cursor.execute(
        """UPDATE realm_catalog SET
               seen_via_transactions = false,
               deployer_address = NULL, deploy_height = NULL, deploy_tx_index = NULL,
               first_seen_height = NULL, last_activity_height = NULL,
               last_activity_tx_index = NULL, last_activity_at = NULL,
               call_count = 0, successful_call_count = 0, failed_call_count = 0,
               unknown_result_call_count = 0, last_counted_height = NULL,
               updated_at = now()
           WHERE chain_id = %s""",
        (chain_id,),
    )
    for (height, block_time), aggregates in block_aggregates.items():
        upsert_transaction_catalog_aggregates(
            cursor, chain_id, height, block_time, aggregates
        )

    cursor.execute(
        """UPDATE realm_catalog_state
           SET activity_from_height = %s, activity_through_height = %s, updated_at = now()
           WHERE chain_id = %s""",
        (from_height, through_height, chain_id),
    )
    if cursor.rowcount != 1:
        raise RebuildError("Realm catalog state update did not affect exactly one row")
    cursor.execute(
        """SELECT count(*) FROM realm_catalog WHERE chain_id = %s AND (
             call_count < 0 OR successful_call_count < 0 OR failed_call_count < 0
             OR unknown_result_call_count < 0
             OR successful_call_count + failed_call_count + unknown_result_call_count <> call_count
             OR (call_count = 0) <> (last_counted_height IS NULL))""",
        (chain_id,),
    )
    if int(cursor.fetchone()[0]) != 0:
        raise RebuildError("rebuilt Realm counter invariants failed")
    return len(unique_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-height", type=int, required=True)
    parser.add_argument("--through-height", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.from_height < 1 or (args.through_height is not None and args.through_height < 1):
        parser.error("heights must be positive")

    config = load_config()
    database = PostgresDatabase(config.database_url)
    checkpoint = database.get_checkpoint(config.chain_id)
    through_height = args.through_height if args.through_height is not None else checkpoint
    if through_height is None or through_height < args.from_height:
        parser.error("activity range must be ordered and within locally indexed blocks")
    try:
        with database.connect() as connection:
            with connection.cursor() as cursor:
                path_count = rebuild_cursor(
                    cursor, config.chain_id, args.from_height, through_height, args.dry_run
                )
            if args.dry_run:
                connection.rollback()
            else:
                connection.commit()
    except RebuildError as exc:
        print(f"Realm activity rebuild failed: {str(exc)[:160]}", file=sys.stderr)
        return 1
    print(f"paths={path_count} from_height={args.from_height} "
          f"through_height={through_height} dry_run={str(args.dry_run).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
