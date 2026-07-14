#!/usr/bin/env python3
"""Run the bounded one-shot PostgreSQL indexer for an explicit finalized range."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import DEFAULT_MAX_HEIGHTS, load_config
from indexer.database import PostgresDatabase
from indexer.rpc import select_rpc
from indexer.service import IndexerService, plan_range


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-height", type=int)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--end-height", type=int)
    group.add_argument("--max-heights", type=int, default=DEFAULT_MAX_HEIGHTS)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        selected_rpc = select_rpc(config.rpc_urls, config.chain_id, config.max_height_lag)
        database = PostgresDatabase(config.database_url)
        checkpoint = None if args.dry_run else database.get_checkpoint(config.chain_id)
        plan = plan_range(
            checkpoint=checkpoint,
            start_height=args.start_height,
            end_height=args.end_height,
            max_heights=args.max_heights,
            finalized_tip=selected_rpc.finalized_tip,
            hard_max=config.hard_max_heights,
            dry_run=args.dry_run,
        )
        service = IndexerService(
            rpc_client=selected_rpc.client,
            db=database,
            chain_id=config.chain_id,
            finalized_tip=selected_rpc.finalized_tip,
            probes=selected_rpc.probes,
        )
        summary = service.run(plan)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode = "dry-run" if summary.dry_run else "write"
    print("Bounded indexer summary")
    print(f"Mode: {mode}")
    print(f"Finalized tip: {summary.plan.finalized_tip}")
    print(f"Requested range: {summary.plan.start_height}-{summary.plan.end_height} ({summary.plan.count} heights)")
    print(f"Processed heights: {', '.join(str(height) for height in summary.processed) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
