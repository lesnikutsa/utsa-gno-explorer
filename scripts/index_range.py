#!/usr/bin/env python3
"""Run the bounded one-shot PostgreSQL indexer for an explicit finalized range."""
from __future__ import annotations
import argparse, sys
from indexer.config import DEFAULT_MAX_HEIGHTS, load_config
from indexer.database import PostgresDatabase
from indexer.rpc import select_rpc
from indexer.service import IndexerService, plan_range


def build_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-height", type=int)
    g=p.add_mutually_exclusive_group()
    g.add_argument("--end-height", type=int)
    g.add_argument("--max-heights", type=int, default=DEFAULT_MAX_HEIGHTS)
    p.add_argument("--dry-run", action="store_true")
    return p

def main(argv=None):
    args=build_parser().parse_args(argv)
    try:
        cfg=load_config()
        selected=select_rpc(cfg.rpc_urls,cfg.chain_id,cfg.max_height_lag)
        db=PostgresDatabase(cfg.database_url)
        checkpoint=None if args.dry_run else db.get_checkpoint()
        plan=plan_range(checkpoint,args.start_height,args.end_height,args.max_heights,selected.finalized_tip,cfg.hard_max_heights,args.dry_run)
        service=IndexerService(selected.client,db,cfg.chain_id,selected.client.base_url.rstrip('/'),selected.finalized_tip)
        summary=service.run(plan)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    mode="dry-run" if summary.dry_run else "write"
    print("Bounded indexer summary")
    print(f"Mode: {mode}")
    print(f"Finalized tip: {summary.plan.finalized_tip}")
    print(f"Requested range: {summary.plan.start_height}-{summary.plan.end_height} ({summary.plan.count} heights)")
    print(f"Processed heights: {', '.join(str(h) for h in summary.processed) or 'none'}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
