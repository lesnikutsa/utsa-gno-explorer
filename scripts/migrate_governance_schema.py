#!/usr/bin/env python3
"""Explicitly apply additive governance persistence migration 0004."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.init_database import (FINAL_SCHEMA_EXPECTATIONS, PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
    PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
    PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS, fetch_schema_snapshot,
    validate_one_of_exact_schema_stages, validate_schema_snapshot, validate_schema_stage)

MIGRATION = ROOT / "database/migrations/0004_add_governance_persistence.sql"
TABLES = {"governance_proposals", "governance_votes", "governance_sync_state"}


def migrate(database_url: str, migration_path: Path = MIGRATION, connect=None) -> str:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            snapshot = fetch_schema_snapshot(cursor)
            present = snapshot.get("tables", set()) & TABLES
            if present and present != TABLES:
                raise RuntimeError("unknown partial governance schema")
            if not present:
                if not snapshot.get("tables"):
                    raise RuntimeError("empty public schema; use python scripts/init_database.py")
                validate_schema_stage(snapshot, PRE_GOVERNANCE_SCHEMA_EXPECTATIONS)
                cursor.execute(migration_path.read_text())
            target = fetch_schema_snapshot(cursor)
            candidates = (
                PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
                PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS,
                FINAL_SCHEMA_EXPECTATIONS,
            )
            expectation = next(
                (item for item in candidates if item["tables"] == target.get("tables", set())),
                PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
            )
            validate_schema_snapshot(target, expectation)
        connection.commit()
    return "applied" if not present else "already-compatible"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--migration", type=Path, default=MIGRATION)
    return result


def _safe(message: str, database_url: str) -> str:
    message = message.replace(database_url, "[redacted DATABASE_URL]") if database_url else message
    return re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1[redacted]@", message)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    database_url = os.getenv("DATABASE_URL", "")
    try:
        action = migrate(database_url, args.migration)
    except Exception as exc:
        print(f"Governance migration failed: {_safe(str(exc), database_url)}", file=sys.stderr)
        return 1
    print(f"Governance migration succeeded: {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
