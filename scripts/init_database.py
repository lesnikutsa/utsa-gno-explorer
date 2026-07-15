#!/usr/bin/env python3
"""Initialize or validate the PostgreSQL schema without exposing DATABASE_URL in argv."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "database" / "schema.sql"
EXPECTED_TABLES = {
    "blocks", "transactions", "validators", "validator_set_members", "validator_signatures", "rpc_endpoints", "rpc_endpoint_checks", "indexer_state",
}
EXPECTED_COLUMNS = {
    "blocks": {"height": ("bigint", "NO"), "block_hash_base64": ("text", "NO"), "block_hash_hex": ("text", "NO"), "time_utc": ("timestamp with time zone", "NO"), "tx_count": ("integer", "NO")},
    "transactions": {"id": ("bigint", "NO"), "block_height": ("bigint", "NO"), "tx_index": ("integer", "NO"), "raw_base64": ("text", "NO"), "decode_status": ("text", "NO")},
    "validators": {"signing_address": ("text", "NO"), "public_key_type": ("text", "NO"), "public_key_value": ("text", "NO"), "first_seen_height": ("bigint", "NO"), "last_seen_height": ("bigint", "NO")},
    "validator_set_members": {"height": ("bigint", "NO"), "signing_address": ("text", "NO"), "voting_power": ("numeric", "NO")},
    "validator_signatures": {"height": ("bigint", "NO"), "signing_address": ("text", "NO"), "vote_status": ("text", "NO"), "signed": ("boolean", "NO")},
    "rpc_endpoints": {"id": ("bigint", "NO"), "url": ("text", "NO"), "chain_id": ("text", "NO"), "is_selected": ("boolean", "NO")},
    "rpc_endpoint_checks": {"id": ("bigint", "NO"), "rpc_endpoint_id": ("bigint", "NO"), "chain_id": ("text", "NO"), "healthy": ("boolean", "NO")},
    "indexer_state": {"state_key": ("text", "NO"), "chain_id": ("text", "NO"), "last_finalized_height": ("bigint", "NO")},
}
EXPECTED_PRIMARY_KEYS = {
    "blocks": ("height",), "transactions": ("id",), "validators": ("signing_address",), "validator_set_members": ("height", "signing_address"), "validator_signatures": ("height", "signing_address"), "rpc_endpoints": ("id",), "rpc_endpoint_checks": ("id",), "indexer_state": ("state_key",),
}
EXPECTED_UNIQUES = {("blocks", ("block_hash_base64",)), ("blocks", ("block_hash_hex",)), ("transactions", ("block_height", "tx_index")), ("validators", ("public_key_type", "public_key_value")), ("rpc_endpoints", ("url",))}
EXPECTED_FOREIGN_KEYS = {("transactions", ("block_height",), "blocks"), ("validator_set_members", ("height",), "blocks"), ("validator_set_members", ("signing_address",), "validators"), ("validator_signatures", ("height", "signing_address"), "validator_set_members"), ("rpc_endpoint_checks", ("rpc_endpoint_id",), "rpc_endpoints")}
EXPECTED_CHECKS = {"blocks_block_hash_hex_uppercase", "transactions_decode_status_consistent", "validators_public_key_unique", "validator_signatures_signed_only_matching_commit", "rpc_endpoints_no_secret_url", "indexer_state_default_key"}
EXPECTED_INDEXES = {
    "blocks_time_utc_idx": {"table": "blocks", "must_contain": ["time_utc DESC"]},
    "validator_set_members_height_power_idx": {"table": "validator_set_members", "must_contain": ["voting_power DESC", "signing_address"]},
    "validator_signatures_height_status_idx": {"table": "validator_signatures", "must_contain": ["height DESC", "vote_status", "signing_address"]},
    "rpc_endpoints_one_selected_per_chain_idx": {"table": "rpc_endpoints", "must_contain": ["UNIQUE", "chain_id", "WHERE is_selected"]},
    "rpc_endpoint_checks_endpoint_time_idx": {"table": "rpc_endpoint_checks", "must_contain": ["rpc_endpoint_id", "checked_at DESC"]},
}

class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing schema is not exactly compatible enough to run."""


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def validate_schema_snapshot(snapshot: dict[str, Any]) -> None:
    tables = set(snapshot.get("tables", set()))
    missing = EXPECTED_TABLES - tables
    if missing:
        raise SchemaCompatibilityError(f"missing expected tables: {', '.join(sorted(missing))}")
    for table, columns in EXPECTED_COLUMNS.items():
        actual = snapshot.get("columns", {}).get(table, {})
        for column, expected in columns.items():
            if column not in actual:
                raise SchemaCompatibilityError(f"missing column {table}.{column}")
            if tuple(actual[column]) != expected:
                raise SchemaCompatibilityError(f"incompatible column {table}.{column}: expected {expected[0]} nullable={expected[1]}")
    for table, columns in EXPECTED_PRIMARY_KEYS.items():
        if tuple(snapshot.get("primary_keys", {}).get(table, ())) != columns:
            raise SchemaCompatibilityError(f"incompatible primary key for {table}")
    uniques = {(table, tuple(cols)) for table, cols in snapshot.get("unique_constraints", set())}
    if not EXPECTED_UNIQUES.issubset(uniques):
        raise SchemaCompatibilityError("missing expected unique constraints")
    fks = {(table, tuple(cols), ref) for table, cols, ref in snapshot.get("foreign_keys", set())}
    if not EXPECTED_FOREIGN_KEYS.issubset(fks):
        raise SchemaCompatibilityError("missing expected foreign keys")
    checks = set(snapshot.get("check_constraints", set()))
    if not EXPECTED_CHECKS.issubset(checks):
        raise SchemaCompatibilityError("missing expected check constraints")
    indexes = snapshot.get("indexes", {})
    for name, expected in EXPECTED_INDEXES.items():
        definition = indexes.get(name)
        if not definition:
            raise SchemaCompatibilityError(f"missing expected index {name}")
        normalized = _norm(definition)
        for part in expected["must_contain"]:
            if part not in normalized:
                raise SchemaCompatibilityError(f"incompatible index {name}")


def fetch_schema_snapshot(cursor) -> dict[str, Any]:
    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    tables = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'public'")
    columns: dict[str, dict[str, tuple[str, str]]] = {}
    for table, column, data_type, nullable in cursor.fetchall():
        columns.setdefault(table, {})[column] = (data_type, nullable)
    cursor.execute("""
        SELECT tc.table_name, tc.constraint_type, tc.constraint_name, kcu.column_name, ccu.table_name
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
        ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position
    """)
    primary: dict[str, list[str]] = {}
    unique: dict[tuple[str, str], list[str]] = {}
    foreign: dict[tuple[str, str, str], list[str]] = {}
    checks: set[str] = set()
    for table, ctype, cname, column, ref_table in cursor.fetchall():
        if ctype == "PRIMARY KEY" and column:
            primary.setdefault(table, []).append(column)
        elif ctype == "UNIQUE" and column:
            unique.setdefault((table, cname), []).append(column)
        elif ctype == "FOREIGN KEY" and column:
            foreign.setdefault((table, cname, ref_table), []).append(column)
        elif ctype == "CHECK":
            checks.add(cname)
    cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    return {
        "tables": tables,
        "columns": columns,
        "primary_keys": {table: tuple(cols) for table, cols in primary.items()},
        "unique_constraints": {(table, tuple(cols)) for (table, _), cols in unique.items()},
        "foreign_keys": {(table, tuple(cols), ref_table) for (table, _, ref_table), cols in foreign.items()},
        "check_constraints": checks,
        "indexes": {name: definition for name, definition in cursor.fetchall()},
    }


def initialize_or_validate(database_url: str, schema_path: Path = SCHEMA, connect=None) -> None:
    if not database_url:
        raise ValueError("DATABASE_URL is required; value is intentionally not printed")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    schema_sql = schema_path.read_text()
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            existing = {row[0] for row in cursor.fetchall()}
            if not existing:
                cursor.execute(schema_sql)
                snapshot = fetch_schema_snapshot(cursor)
                validate_schema_snapshot(snapshot)
            else:
                validate_schema_snapshot(fetch_schema_snapshot(cursor))
        connection.commit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default=str(SCHEMA), help="Schema SQL file to apply to an empty database.")
    return parser


def _sanitize_message(message: str, database_url: str) -> str:
    sanitized = message.replace(database_url, "[redacted DATABASE_URL]") if database_url else message
    return re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1[redacted]@", sanitized)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        initialize_or_validate(database_url, Path(args.schema))
    except Exception as exc:
        print(f"Schema initialization failed: {exc.__class__.__name__}: {_sanitize_message(str(exc), database_url)}", file=sys.stderr)
        return 1
    print("Schema initialization/validation succeeded")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
