#!/usr/bin/env python3
"""Explicitly apply additive RPC latency snapshot migration 0005."""
from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.init_database import FINAL_SCHEMA_EXPECTATIONS, fetch_schema_snapshot, validate_schema_snapshot

MIGRATION = ROOT / "database/migrations/0005_add_rpc_endpoint_latency.sql"


def _pre_migration_expectations():
    expected = copy.deepcopy(FINAL_SCHEMA_EXPECTATIONS)
    del expected["columns"]["rpc_endpoints"]["latency_ms"]
    del expected["check_constraints"]["rpc_endpoints_latency_ms_check"]
    return expected


def migrate(database_url: str, migration_path: Path = MIGRATION, connect=None) -> str:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            before = fetch_schema_snapshot(cursor)
            column_present = "latency_ms" in before.get("columns", {}).get("rpc_endpoints", {})
            constraint_present = "rpc_endpoints_latency_ms_check" in before.get("check_constraints", {})
            if column_present != constraint_present:
                raise RuntimeError("unknown partial RPC latency schema")
            validate_schema_snapshot(before, FINAL_SCHEMA_EXPECTATIONS if column_present else _pre_migration_expectations())
            cursor.execute(migration_path.read_text())
            validate_schema_snapshot(fetch_schema_snapshot(cursor), FINAL_SCHEMA_EXPECTATIONS)
        connection.commit()
    return "already-compatible" if column_present else "applied"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", type=Path, default=MIGRATION)
    args = parser.parse_args(argv)
    database_url = os.getenv("DATABASE_URL", "")
    try:
        action = migrate(database_url, args.migration)
    except Exception as exc:
        message = str(exc).replace(database_url, "[redacted DATABASE_URL]") if database_url else str(exc)
        message = re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1[redacted]@", message)
        print(f"RPC latency migration failed: {message}", file=sys.stderr)
        return 1
    print(f"RPC latency migration succeeded: {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
