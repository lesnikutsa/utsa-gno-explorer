#!/usr/bin/env python3
"""Inspect GovDAO renders without modifying application state."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from governance import (
    DEFAULT_REALM,
    MAX_GOVERNANCE_PAGES,
    MAX_GOVERNANCE_PROPOSALS,
    GovernanceParseError,
    GovernanceSource,
    discover_governance,
)
from indexer.rpc import select_rpc
from scripts.inspect_rpc import RpcError, configured_chain_id, configured_max_height_lag, configured_rpc_urls, load_dotenv


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--realm")
    result.add_argument("--proposal", type=int)
    result.add_argument("--raw-dir", type=Path)
    result.add_argument("--include-raw", action="store_true")
    result.add_argument("--json", action="store_true")
    result.add_argument("--timeout", type=int, default=10)
    result.add_argument("--max-pages", type=int, default=100)
    result.add_argument("--max-proposals", type=int, default=1000)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    load_dotenv()
    realm = args.realm or os.environ.get("GNO_GOVERNANCE_REALM", "").strip() or DEFAULT_REALM
    if (
        not realm.startswith("gno.land/r/")
        or ":" in realm
        or not 1 <= args.timeout <= 60
        or args.proposal is not None and args.proposal < 0
        or not 1 <= args.max_pages <= MAX_GOVERNANCE_PAGES
        or not 1 <= args.max_proposals <= MAX_GOVERNANCE_PROPOSALS
    ):
        print("error: invalid governance configuration", file=sys.stderr)
        return 2
    try:
        selected = select_rpc(configured_rpc_urls(), configured_chain_id(), configured_max_height_lag(), args.timeout)
        source = GovernanceSource(configured_chain_id(), selected.client.base_url.rstrip("/"), selected.latest_height, realm)
        raw_sink = None
        if args.raw_dir:
            def write_raw(name: str, render: str) -> None:
                args.raw_dir.mkdir(parents=True, exist_ok=True)
                target = args.raw_dir / (name.replace("/", "_").replace("?", "_") + ".md")
                target.write_text(render, encoding="utf-8")
            raw_sink = write_raw
        discovery = discover_governance(
            selected.client, source, args.max_pages, args.max_proposals, args.proposal,
            capture_raw=args.include_raw, raw_sink=raw_sink,
        )
        if args.json:
            print(json.dumps(discovery.to_dict(args.include_raw), ensure_ascii=False, sort_keys=True))
        else:
            print(f"Governance realm: {realm}")
            print(f"RPC: {source.rpc_url} (height {source.observed_height})")
            print(f"Proposals: {len(discovery.proposals)}; pages: {discovery.page_count}; complete: {str(discovery.complete).lower()}")
            for proposal in discovery.proposals:
                print(f"#{proposal.proposal_id} [{proposal.status}] {proposal.title}")
        for warning in discovery.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    except RpcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (GovernanceParseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
