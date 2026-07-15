#!/usr/bin/env python3
"""Run the foreground continuous PostgreSQL indexer with bounded catch-up."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config, load_continuous_config
from indexer.database import PostgresDatabase
from indexer.runner import ContinuousConfig, StopController, install_signal_handlers, run_continuous


def build_parser() -> argparse.ArgumentParser:
    defaults = load_continuous_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-height", type=int, default=defaults.start_height)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--batch-size", type=int, default=defaults.batch_size)
    parser.add_argument("--poll-interval-seconds", type=int, default=defaults.poll_interval_seconds)
    parser.add_argument("--error-backoff-seconds", type=int, default=defaults.error_backoff_seconds)
    parser.add_argument("--max-backoff-seconds", type=int, default=defaults.max_backoff_seconds)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    config = load_config()
    continuous = ContinuousConfig(
        start_height=args.start_height,
        once=args.once,
        max_cycles=args.max_cycles,
        batch_size=args.batch_size,
        poll_interval_seconds=args.poll_interval_seconds,
        error_backoff_seconds=args.error_backoff_seconds,
        max_backoff_seconds=args.max_backoff_seconds,
    )
    stop = StopController()
    install_signal_handlers(stop)
    return run_continuous(PostgresDatabase(config.database_url), config.chain_id, config.rpc_urls, config.max_height_lag, continuous, stop=stop)


if __name__ == "__main__":
    raise SystemExit(main())
