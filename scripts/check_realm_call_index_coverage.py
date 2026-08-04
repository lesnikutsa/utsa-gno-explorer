#!/usr/bin/env python3
"""Inspect Realm call index coverage without modifying PostgreSQL."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from indexer.config import load_config
from indexer.database import PostgresDatabase

def run(database_url: str | None = None) -> int:
    try:
        config=load_config(); database=PostgresDatabase(database_url or config.database_url)
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT from_height,through_height FROM realm_call_index_state WHERE chain_id=%s",(config.chain_id,)); state=cursor.fetchone()
            cursor.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key='default' AND chain_id=%s",(config.chain_id,)); indexed=cursor.fetchone()
            cursor.execute("SELECT count(*) FROM realm_call_index WHERE chain_id=%s",(config.chain_id,)); count=int(cursor.fetchone()[0])
        if state is None:
            print(f"chain_id={config.chain_id} call_index_from=missing call_index_through=missing indexed_height={indexed[0] if indexed else 'missing'} row_count={count} contiguous=false rebuild_required=true"); return 2
        current=int(indexed[0]) if indexed else None; contiguous=current is not None and int(state[1]) == current
        print(f"chain_id={config.chain_id} call_index_from={state[0]} call_index_through={state[1]} indexed_height={current if current is not None else 'missing'} row_count={count} contiguous={str(contiguous).lower()} rebuild_required={str(not contiguous).lower()}")
        return 0 if contiguous else 3
    except Exception as exc:
        print(f"status=error error={type(exc).__name__}",file=sys.stderr); return 4
if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--database-url"); args=parser.parse_args(); raise SystemExit(run(args.database_url))
