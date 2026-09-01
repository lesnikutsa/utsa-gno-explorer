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

from scripts.init_database import (
    BASE_LEGACY_EXPECTATIONS, FINAL_SCHEMA_EXPECTATIONS,
    PRE_GOVERNANCE_SCHEMA_EXPECTATIONS, PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
    PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
    PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS, TRANSACTION_HASH_ONLY_EXPECTATIONS,
    PRE_REALM_CATALOG_EXPECTATIONS,
    PRE_COSMOS_VALIDATOR_SNAPSHOT_EXPECTATIONS,
    VALOPERS_ONLY_EXPECTATIONS, fetch_schema_snapshot,
    validate_one_of_exact_schema_stages, validate_schema_snapshot,
)

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
            if not tables:
                raise MigrationPreconditionError(
                    "empty public schema; use python scripts/init_database.py"
                )
            allowed_table_sets = {
                frozenset(expectations["tables"]) for expectations in (
                    BASE_LEGACY_EXPECTATIONS, TRANSACTION_HASH_ONLY_EXPECTATIONS,
                    VALOPERS_ONLY_EXPECTATIONS, PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
                    PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
                    PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
                    PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS,
                    PRE_REALM_CATALOG_EXPECTATIONS,
                    PRE_COSMOS_VALIDATOR_SNAPSHOT_EXPECTATIONS,
                    FINAL_SCHEMA_EXPECTATIONS,
                )
            }
            if frozenset(tables) not in allowed_table_sets:
                raise MigrationPreconditionError("public schema is not an exact supported stage")
            snapshot = fetch_schema_snapshot(cursor)
            try:
                stage = validate_one_of_exact_schema_stages(snapshot, {
                    "base": BASE_LEGACY_EXPECTATIONS,
                    "transaction-hash-only": TRANSACTION_HASH_ONLY_EXPECTATIONS,
                    "valopers-only": VALOPERS_ONLY_EXPECTATIONS,
                    "pre-network": PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
                    "pre-governance": PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
                    "governance": PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
                    "participants": PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS,
                    "execution-results": PRE_REALM_CATALOG_EXPECTATIONS,
                    "pre-cosmos-snapshots": PRE_COSMOS_VALIDATOR_SNAPSHOT_EXPECTATIONS,
                    "final": FINAL_SCHEMA_EXPECTATIONS,
                })
            except Exception as exc:
                raise MigrationPreconditionError("public schema is not an exact supported stage") from exc
            if stage in {"valopers-only", "pre-network", "pre-governance", "governance", "participants", "execution-results", "pre-cosmos-snapshots", "final"}:
                return "already-compatible"

            cursor.execute(migration_sql)
            target = VALOPERS_ONLY_EXPECTATIONS if stage == "base" else PRE_NETWORK_DISTRIBUTION_EXPECTATIONS
            validate_schema_snapshot(fetch_schema_snapshot(cursor), target)
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
