#!/usr/bin/env python3
"""Explicit one-shot rebuild of transaction-derived Realm catalog aggregates."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.realm_catalog import aggregate_block

LOCK_ID=0x5245414C4D524542

def rebuild_cursor(cursor, chain_id, from_height, through_height, dry_run=False):
    cursor.execute("SELECT pg_advisory_xact_lock(%s)",(LOCK_ID,))
    cursor.execute("""SELECT t.block_height,t.tx_index,t.payload_summary,e.execution_status,b.time_utc
      FROM transactions t JOIN blocks b ON b.height=t.block_height LEFT JOIN transaction_execution_results e
      ON e.block_height=t.block_height AND e.tx_index=t.tx_index WHERE t.block_height BETWEEN %s AND %s
      ORDER BY t.block_height,t.tx_index""",(from_height,through_height))
    grouped={}
    for height,index,summary,status,block_time in cursor.fetchall(): grouped.setdefault((int(height),block_time),[]).append((int(index),summary,status))
    aggregates=[(height,block_time,item) for (height,block_time),txs in grouped.items() for item in aggregate_block(txs)]
    if dry_run: return len(aggregates)
    cursor.execute("""UPDATE realm_catalog SET seen_via_transactions=false,deployer_address=NULL,deploy_height=NULL,
      deploy_tx_index=NULL,first_seen_height=NULL,last_activity_height=NULL,last_activity_tx_index=NULL,
      last_activity_at=NULL,call_count=0,successful_call_count=0,failed_call_count=0,
      unknown_result_call_count=0,last_counted_height=NULL,updated_at=now() WHERE chain_id=%s""",(chain_id,))
    # Reuse the same invariant-preserving statement used by the continuous indexer through compact synthetic rows.
    from types import SimpleNamespace
    from indexer.database import _upsert_realm_catalog
    for height,block_time in grouped:
        txs=grouped[(height,block_time)]
        transactions=[{"index":i,"decode_status":"decoded","payload_summary":s} for i,s,_ in txs]
        results=[{"tx_index":i,"execution_status":status} for i,_,status in txs if status]
        _upsert_realm_catalog(cursor,SimpleNamespace(height=height,block={"time":block_time},transactions=transactions,execution_results=results),chain_id)
    cursor.execute("""UPDATE realm_catalog_state SET activity_from_height=%s,activity_through_height=%s,updated_at=now()
      WHERE chain_id=%s""",(from_height,through_height,chain_id))
    return len(aggregates)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--from-height',type=int,required=True); parser.add_argument('--through-height',type=int); parser.add_argument('--dry-run',action='store_true'); args=parser.parse_args()
    if args.from_height < 1 or (args.through_height is not None and args.through_height < 1): parser.error('heights must be positive')
    config=load_config(); db=PostgresDatabase(config.database_url); checkpoint=db.get_checkpoint(config.chain_id); through=args.through_height or checkpoint
    if checkpoint is None or through < args.from_height or through > checkpoint: parser.error('range is outside locally indexed blocks')
    with db.connect() as connection:
      with connection.cursor() as cursor: count=rebuild_cursor(cursor,config.chain_id,args.from_height,through,args.dry_run)
      if args.dry_run: connection.rollback()
      else: connection.commit()
    print(f"paths={count} from_height={args.from_height} through_height={through} dry_run={str(args.dry_run).lower()}")
    return 0
if __name__=='__main__': sys.exit(main())
