#!/usr/bin/env python3
"""Run the sequential Governance updater in the foreground."""
from __future__ import annotations
import argparse, logging, os, signal, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from indexer.config import load_governance_updater_config
from indexer.database import PostgresDatabase
from indexer.governance_updater import run_updater
from indexer.runner import StopController

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--full-once", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args(argv)
    try:
        config = load_governance_updater_config()
        if args.max_cycles is not None and args.max_cycles < 1:
            raise ValueError("--max-cycles must be positive")
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
        stop = StopController()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda sig, frame: stop.request_stop(signal.Signals(sig).name))
        return run_updater(config, PostgresDatabase(config.database_url), stop,
                           once=args.once, full_once=args.full_once, max_cycles=args.max_cycles)
    except Exception as exc:
        print(f"Governance updater failed: {type(exc).__name__}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
