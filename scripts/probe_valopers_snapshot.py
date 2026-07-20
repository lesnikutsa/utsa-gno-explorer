#!/usr/bin/env python3
"""Collect one complete, bounded Valopers registry snapshot in memory."""
from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.valopers_snapshot import collect_valopers_snapshot
from scripts.inspect_rpc import configured_chain_id, configured_rpc_urls, parse_status, select_healthy_rpc


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Collect a bounded Valopers registry snapshot")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    del args
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            client, status_payload = select_healthy_rpc(
                configured_rpc_urls(), expected_chain_id=configured_chain_id()
            )
        source_height = parse_status(status_payload)["latest_height"]
        if not isinstance(source_height, int) or isinstance(source_height, bool) or source_height < 1:
            raise ValueError("invalid source height")
        snapshot = collect_valopers_snapshot(client, source_height)
    except Exception:
        print("Valopers snapshot failed: collection did not complete", file=sys.stderr)
        return 1

    first = snapshot.profiles[0].moniker if snapshot.profiles else ""
    last = snapshot.profiles[-1].moniker if snapshot.profiles else ""
    unique_signing = len({profile.signing_address for profile in snapshot.profiles})
    print(
        f"source_height={snapshot.source_height} pages={snapshot.page_count} "
        f"profiles={len(snapshot.profiles)} first_moniker={first!r} "
        f"last_moniker={last!r} unique_signing_addresses={unique_signing}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
