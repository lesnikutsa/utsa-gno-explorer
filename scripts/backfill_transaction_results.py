#!/usr/bin/env python3
"""Backfill missing local transaction execution results without moving checkpoint."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.execution_backfill import backfill_height, missing_heights
from indexer.rpc import probe_rpc_endpoints


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-height", type=int)
    parser.add_argument("--end-height", type=int)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.batch_size < 1: parser.error("--batch-size must be positive")
    config = load_config(); db = PostgresDatabase(config.database_url)
    probes = probe_rpc_endpoints(config.rpc_urls, config.chain_id, config.max_height_lag)
    while True:
        with db.connect() as connection, connection.cursor() as cursor:
            heights = missing_heights(cursor, args.start_height, args.end_height, args.batch_size)
        if not heights: return 0
        for height in heights:
            print(f"backfill height={height}", flush=True)
            backfill_height(db, height, probes)
        if args.once: return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted; completed heights remain committed", file=sys.stderr)
        raise SystemExit(130)
