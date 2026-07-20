#!/usr/bin/env python3
"""Collect and atomically persist one pinned Valopers snapshot."""
from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.database import PostgresDatabase
from indexer.valopers_snapshot import collect_valopers_snapshot
from scripts.inspect_rpc import configured_chain_id, configured_rpc_urls, parse_status, select_healthy_rpc


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Persist one complete pinned Valopers snapshot")


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    try:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            client, status_payload = select_healthy_rpc(
                configured_rpc_urls(), expected_chain_id=configured_chain_id()
            )
        source_height = parse_status(status_payload)["latest_height"]
        if not isinstance(source_height, int) or isinstance(source_height, bool) or source_height < 1:
            raise ValueError("invalid latest height")
        snapshot = collect_valopers_snapshot(client, source_height)
        result = PostgresDatabase(database_url).replace_valopers_snapshot(snapshot, configured_chain_id())
    except Exception:
        print("Valopers snapshot persistence failed", file=sys.stderr)
        return 1
    print(
        f"Valopers snapshot persisted: action={result.action} source_height={result.source_height} "
        f"pages={result.page_count} profiles={result.profile_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
