#!/usr/bin/env python3
"""Wait for PostgreSQL readiness using DATABASE_URL without printing secrets."""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

_STOP = False


def _request_stop(signum, frame):
    global _STOP
    _STOP = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0, help="Maximum seconds to wait before failing.")
    parser.add_argument("--retry-interval", type=float, default=2.0, help="Seconds between connection attempts.")
    return parser


def is_permanent_connection_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    permanent_markers = ("invalid dsn", "missing =", "invalid connection option", "unsupported connection option", "could not parse", "malformed")
    return name in {"programmingerror"} or any(marker in message for marker in permanent_markers)


def wait_for_postgres(database_url: str, timeout: float, retry_interval: float, connect=None, sleep=time.sleep, monotonic=time.monotonic) -> bool:
    if not database_url:
        print("PostgreSQL readiness failed: DATABASE_URL is not set", file=sys.stderr)
        return False
    if timeout < 0 or retry_interval <= 0:
        raise ValueError("timeout must be non-negative and retry interval must be positive")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    deadline = monotonic() + timeout
    while not _STOP:
        try:
            with connect(database_url, connect_timeout=max(1, min(5, int(retry_interval)))):
                print("PostgreSQL is ready")
                return True
        except Exception as exc:  # readiness probe intentionally retries transient driver errors
            if is_permanent_connection_error(exc):
                print(f"PostgreSQL readiness failed: {exc.__class__.__name__}", file=sys.stderr)
                return False
            if monotonic() >= deadline:
                print(f"PostgreSQL readiness timed out after {timeout:g}s: {exc.__class__.__name__}", file=sys.stderr)
                return False
            sleep(min(retry_interval, max(0.0, deadline - monotonic())))
    print("PostgreSQL readiness interrupted", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    args = build_parser().parse_args(argv)
    try:
        return 0 if wait_for_postgres(os.environ.get("DATABASE_URL", ""), args.timeout, args.retry_interval) else 1
    except ValueError as exc:
        print(f"fatal configuration error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
