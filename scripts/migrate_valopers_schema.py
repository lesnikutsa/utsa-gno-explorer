#!/usr/bin/env python3
"""Explicitly add and validate the Valopers persistence schema."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.init_database import EXPECTED_TABLES, fetch_schema_snapshot, validate_schema_snapshot

MIGRATION = REPO_ROOT / "database" / "migrations" / "0001_add_valopers_persistence.sql"
LEGACY_TABLES = {
    "blocks", "transactions", "validators", "validator_set_members",
    "validator_signatures", "rpc_endpoints", "rpc_endpoint_checks", "indexer_state",
}
NEW_TABLES = {"valoper_profiles", "valopers_snapshot_state"}


class MigrationPreconditionError(RuntimeError):
    """Raised when migration cannot safely start from the current catalog."""


def migrate_valopers_schema(database_url: str, migration_path: Path = MIGRATION, connect=None) -> str:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if connect is None:
        import psycopg
        connect = psycopg.connect

    migration_sql = migration_path.read_text()
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.relname FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                ORDER BY c.relname
            """)
            tables = {row[0] for row in cursor.fetchall()}
            if tables == EXPECTED_TABLES:
                validate_schema_snapshot(fetch_schema_snapshot(cursor))
                return "already-compatible"
            if tables != LEGACY_TABLES:
                if not tables:
                    raise MigrationPreconditionError(
                        "empty public schema; use python scripts/init_database.py"
                    )
                raise MigrationPreconditionError("public schema is not the exact legacy schema")

            cursor.execute(migration_sql)
            validate_schema_snapshot(fetch_schema_snapshot(cursor))
        connection.commit()
    return "applied"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", default=str(MIGRATION), help="Additive Valopers migration SQL file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        result = migrate_valopers_schema(database_url, Path(args.migration))
    except Exception as exc:
        if isinstance(exc, MigrationPreconditionError) and "empty public schema" in str(exc):
            print("Empty database; use python scripts/init_database.py", file=sys.stderr)
        print("Valopers schema migration failed", file=sys.stderr)
        return 1
    if result == "already-compatible":
        print("Valopers schema is already compatible")
    else:
        print("Valopers schema migration applied and validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
