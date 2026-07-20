#!/usr/bin/env python3
"""Synchronize public Valopers profiles once at a pinned chain height."""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.rpc import select_rpc
from indexer.validator_profiles import DEFAULT_REALM, collect_profiles, match_profiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch, read validator identities, and match without database writes")
    return parser


def safe_error_message(exc: Exception, database_url: str, rpc_urls: list[str]) -> str:
    """Return a bounded category without echoing endpoints, payloads, or secrets."""
    categories = {
        "ProfileSourceError": "Valopers source validation failed",
        "RpcError": "RPC selection or query failed",
        "DatabaseError": "database operation failed",
        "ValueError": "configuration validation failed",
    }
    return categories.get(exc.__class__.__name__, "validator profile synchronization failed")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        selected = select_rpc(config.rpc_urls, config.chain_id, config.max_height_lag)
        source_height = selected.latest_height
        realm = os.environ.get("VALOPERS_REALM_PATH", DEFAULT_REALM).strip() or DEFAULT_REALM
        if realm != DEFAULT_REALM:
            raise ValueError(f"VALOPERS_REALM_PATH must be {DEFAULT_REALM}")
        fetched = collect_profiles(selected.client, source_height, realm)
        database = PostgresDatabase(config.database_url)
        validator_keys = database.load_validator_keys()
        profiles = match_profiles(fetched.profiles, validator_keys)
        writes = 0 if args.dry_run else database.upsert_validator_profiles(profiles)
    except Exception as exc:
        config_value = locals().get("config")
        print(f"Error: {safe_error_message(exc, getattr(config_value, 'database_url', ''), getattr(config_value, 'rpc_urls', []))}", file=sys.stderr)
        return 1

    counts = Counter(profile.match_status for profile in profiles)
    print("Valopers profile sync summary")
    print(f"Mode: {'dry-run' if args.dry_run else 'write'}")
    print(f"Source height: {source_height}")
    print(f"Profiles discovered: {len(profiles)}")
    print(f"Matched: {counts['matched']}")
    print(f"Unmatched: {counts['unmatched']}")
    print(f"Invalid pubkey: {counts['invalid_pubkey']}")
    print(f"Ambiguous: {counts['ambiguous']}")
    print(f"Database writes: {writes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
