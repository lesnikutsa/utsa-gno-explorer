#!/usr/bin/env python3
"""Rebuild the compact Realm call locator index from local bounded summaries."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase, lock_realm_call_index
from indexer.realm_catalog import extract_realm_calls


class RebuildError(RuntimeError):
    """A call-index rebuild safety invariant failed."""


def rebuild_cursor(cursor, chain_id: str, start: int, through: int,
                   dry_run: bool = False) -> int:
    """Replace one bounded range while holding the shared transaction lock.

    Summaries are currently materialized in memory. Operators should split very large
    historical ranges until representative production memory measurements exist.
    """
    if (isinstance(start, bool) or not isinstance(start, int)
            or isinstance(through, bool) or not isinstance(through, int)
            or start < 1 or through < start):
        raise RebuildError("range must contain ordered positive heights")

    lock_realm_call_index(cursor)
    cursor.execute(
        "SELECT last_finalized_height FROM indexer_state "
        "WHERE state_key = 'default' AND chain_id = %s",
        (chain_id,),
    )
    checkpoint = cursor.fetchone()
    if checkpoint is None or through > int(checkpoint[0]):
        raise RebuildError("range exceeds the indexed checkpoint")

    cursor.execute(
        "SELECT count(*), min(height), max(height) FROM blocks "
        "WHERE height BETWEEN %s AND %s",
        (start, through),
    )
    count, minimum, maximum = cursor.fetchone()
    if int(count) != through - start + 1 or minimum != start or maximum != through:
        raise RebuildError("range contains missing local blocks")

    cursor.execute(
        "SELECT from_height, through_height FROM realm_call_index_state "
        "WHERE chain_id = %s FOR UPDATE",
        (chain_id,),
    )
    state = cursor.fetchone()
    if state is not None and (through < int(state[0]) - 1 or start > int(state[1]) + 1):
        raise RebuildError("range is separated from existing coverage by a gap")

    cursor.execute(
        "SELECT block_height, tx_index, payload_summary FROM transactions "
        "WHERE block_height BETWEEN %s AND %s ORDER BY block_height, tx_index",
        (start, through),
    )
    rows = [
        (int(height), int(tx_index), extract_realm_calls(summary))
        for height, tx_index, summary in cursor.fetchall()
    ]
    expected = sum(len(calls) for _, _, calls in rows)
    if dry_run:
        return expected

    cursor.execute(
        "DELETE FROM realm_call_index WHERE chain_id = %s "
        "AND block_height BETWEEN %s AND %s",
        (chain_id, start, through),
    )
    inserted = 0
    positions: set[tuple[int, int, int]] = set()
    for height, tx_index, calls in rows:
        for call in calls:
            position = (height, tx_index, call.message_index)
            if position in positions:
                raise RebuildError("duplicate Realm call position")
            positions.add(position)
            cursor.execute(
                "INSERT INTO realm_call_index(chain_id, block_height, tx_index, "
                "message_index, path, caller_address, function_name, args_count, send_amount) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (chain_id, height, tx_index, call.message_index, call.path,
                 call.caller_address, call.function_name, call.args_count,
                 call.send_amount),
            )
            if cursor.rowcount != 1:
                raise RebuildError("Realm call insert did not affect exactly one row")
            inserted += 1
    if inserted != expected or inserted != len(positions):
        raise RebuildError("Realm call rebuild count mismatch")

    union_start = min(start, int(state[0])) if state else start
    union_through = max(through, int(state[1])) if state else through
    cursor.execute(
        "INSERT INTO realm_call_index_state(chain_id, from_height, through_height) "
        "VALUES (%s, %s, %s) ON CONFLICT(chain_id) DO UPDATE SET "
        "from_height = EXCLUDED.from_height, through_height = EXCLUDED.through_height, "
        "updated_at = now()",
        (chain_id, union_start, union_through),
    )
    if cursor.rowcount != 1:
        raise RebuildError("Realm call state write did not affect exactly one row")
    return inserted


def _safe_error(exc: Exception, database_url: str) -> str:
    message = str(exc).replace(database_url, "[redacted DATABASE_URL]") if database_url else str(exc)
    message = re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1[redacted]@", message)
    return message[:160]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-height", type=int, required=True)
    parser.add_argument("--through-height", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url")
    args = parser.parse_args()
    config = load_config()
    database_url = args.database_url or config.database_url
    database = PostgresDatabase(database_url)
    through = args.through_height
    if through is None:
        through = database.get_checkpoint(config.chain_id)
    if through is None:
        parser.error("no indexed checkpoint")
    try:
        with database.connect() as connection:
            with connection.cursor() as cursor:
                count = rebuild_cursor(
                    cursor, config.chain_id, args.from_height, through, args.dry_run
                )
            if args.dry_run:
                connection.rollback()
            else:
                connection.commit()
    except Exception as exc:
        print(f"Realm call index rebuild failed: {_safe_error(exc, database_url)}", file=sys.stderr)
        return 1
    print(
        f"calls={count} from_height={args.from_height} through_height={through} "
        f"dry_run={str(args.dry_run).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
