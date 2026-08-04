#!/usr/bin/env python3
"""Rebuild the compact Realm call locator index from local bounded summaries."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.realm_catalog import extract_realm_calls

LOCK_ID = 0x52434C4C494458

class RebuildError(RuntimeError):
    """A call-index rebuild safety invariant failed."""

def rebuild_cursor(cursor, chain_id: str, start: int, through: int, dry_run: bool = False) -> int:
    if isinstance(start, bool) or isinstance(through, bool) or start < 1 or through < start:
        raise RebuildError("range must contain ordered positive heights")
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
    cursor.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key='default' AND chain_id=%s", (chain_id,))
    checkpoint = cursor.fetchone()
    if checkpoint is None or through > int(checkpoint[0]):
        raise RebuildError("range exceeds the indexed checkpoint")
    cursor.execute("SELECT count(*),min(height),max(height) FROM blocks WHERE height BETWEEN %s AND %s", (start, through))
    count, minimum, maximum = cursor.fetchone()
    if int(count) != through-start+1 or minimum != start or maximum != through:
        raise RebuildError("range contains missing local blocks")
    cursor.execute("SELECT from_height,through_height FROM realm_call_index_state WHERE chain_id=%s FOR UPDATE", (chain_id,))
    state = cursor.fetchone()
    if state is not None and (through < int(state[0])-1 or start > int(state[1])+1):
        raise RebuildError("range is separated from existing coverage by a gap")
    cursor.execute("SELECT block_height,tx_index,payload_summary FROM transactions WHERE block_height BETWEEN %s AND %s ORDER BY block_height,tx_index", (start, through))
    rows = [(int(height), int(tx), extract_realm_calls(summary)) for height, tx, summary in cursor.fetchall()]
    total = sum(len(calls) for _, _, calls in rows)
    if dry_run:
        return total
    cursor.execute("DELETE FROM realm_call_index WHERE chain_id=%s AND block_height BETWEEN %s AND %s", (chain_id,start,through))
    for height, tx_index, calls in rows:
        for call in calls:
            cursor.execute("INSERT INTO realm_call_index(chain_id,block_height,tx_index,message_index,path,caller_address,function_name,args_count,send_amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (chain_id,height,tx_index,call.message_index,call.path,call.caller_address,call.function_name,call.args_count,call.send_amount))
    union_start = min(start, int(state[0])) if state else start
    union_through = max(through, int(state[1])) if state else through
    cursor.execute("INSERT INTO realm_call_index_state(chain_id,from_height,through_height) VALUES (%s,%s,%s) ON CONFLICT(chain_id) DO UPDATE SET from_height=EXCLUDED.from_height,through_height=EXCLUDED.through_height,updated_at=now()", (chain_id,union_start,union_through))
    return total

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-height",type=int,required=True); parser.add_argument("--through-height",type=int)
    parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--database-url")
    args=parser.parse_args(); config=load_config(); database=PostgresDatabase(args.database_url or config.database_url)
    through=args.through_height if args.through_height is not None else database.get_checkpoint(config.chain_id)
    if through is None: parser.error("no indexed checkpoint")
    try:
        with database.connect() as connection:
            with connection.cursor() as cursor: count=rebuild_cursor(cursor,config.chain_id,args.from_height,through,args.dry_run)
            connection.rollback() if args.dry_run else connection.commit()
    except RebuildError as exc:
        print(f"Realm call index rebuild failed: {exc}",file=sys.stderr); return 1
    print(f"calls={count} from_height={args.from_height} through_height={through} dry_run={str(args.dry_run).lower()}"); return 0
if __name__ == "__main__": raise SystemExit(main())
