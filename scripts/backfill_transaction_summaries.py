#!/usr/bin/env python3
"""Manually backfill a bounded batch of persisted transaction summaries."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_transaction_decoder_config
from indexer.database import PostgresDatabase
from indexer.transaction_decoder import JsonlTransactionDecoder
from indexer.transaction_summary_backfill import (
    process_candidates, release_advisory_lock, select_candidates, try_advisory_lock,
)


def bounded_integer(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return number
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="decode without updating (default)")
    mode.add_argument("--apply", action="store_true", help="conditionally persist stable summaries")
    parser.add_argument("--limit", type=bounded_integer(1, 100), default=25)
    parser.add_argument("--sleep-ms", type=bounded_integer(0, 5000), default=250)
    return parser


def _progress(candidate, outcome: str) -> None:
    print(f"block_height={candidate.block_height} tx_index={candidate.tx_index} result={outcome}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "apply" if args.apply else "dry-run"
    print("Transaction summary backfill")
    print(f"Mode: {mode}\nLimit: {args.limit}\nSleep: {args.sleep_ms} ms")
    connection = decoder = None
    locked = False
    try:
        decoder_config = load_transaction_decoder_config()
        path = decoder_config.executable_path
        if not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise ValueError("transaction decoder executable is unavailable")
        connection = PostgresDatabase(os.environ.get("DATABASE_URL", "").strip()).connect()
        connection.autocommit = True
        if not try_advisory_lock(connection):
            print("Backfill is already running.", file=sys.stderr)
            return 2
        locked = True
        candidates = select_candidates(connection, args.limit)
        decoder = JsonlTransactionDecoder(
            [path], decoder_config.expected_chain_family, decoder_config.timeout_seconds,
            decoder_config.restart_backoff_seconds,
        )
        result = process_candidates(
            connection, decoder, candidates, apply=args.apply,
            sleep_ms=args.sleep_ms, progress=_progress,
        )
        print("Summary")
        for field in ("selected", "decoded", "parsed", "unsupported", "updated", "dry_run", "decode_failed", "skipped_race"):
            print(f"{field}: {getattr(result, field)}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Backfill failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    except Exception:
        print("Backfill failed: database operation failed", file=sys.stderr)
        return 1
    finally:
        if decoder is not None:
            decoder.close()
        if connection is not None:
            if locked:
                try:
                    release_advisory_lock(connection)
                except Exception:
                    pass
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
