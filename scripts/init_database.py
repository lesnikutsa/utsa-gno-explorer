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
    "blocks": {
        "height": ("bigint", "NO", "", None), "block_hash_base64": ("text", "NO", "", None), "block_hash_hex": ("text", "NO", "", None),
        "time_utc": ("timestamp with time zone", "NO", "", None), "proposer_address": ("text", "YES", "", None), "tx_count": ("integer", "NO", "", None),
        "raw_block_response": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "transactions": {
        "id": ("bigint", "NO", "a", None), "block_height": ("bigint", "NO", "", None), "tx_index": ("integer", "NO", "", None), "raw_base64": ("text", "NO", "", None),
        "raw_base64_length": ("integer", "NO", "", None), "decoded_bytes": ("bytea", "YES", "", None), "decoded_byte_length": ("integer", "YES", "", None),
        "decode_status": ("text", "NO", "", None), "payload_summary": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validators": {
        "signing_address": ("text", "NO", "", None), "public_key_type": ("text", "NO", "", None), "public_key_value": ("text", "NO", "", None),
        "first_seen_height": ("bigint", "NO", "", None), "last_seen_height": ("bigint", "NO", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validator_set_members": {
        "height": ("bigint", "NO", "", None), "signing_address": ("text", "NO", "", None), "voting_power": ("numeric(78,0)", "NO", "", None),
        "proposer_priority": ("numeric(78,0)", "YES", "", None), "validator_index": ("integer", "YES", "", None), "raw_validator": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validator_signatures": {
        "height": ("bigint", "NO", "", None), "signing_address": ("text", "NO", "", None), "vote_status": ("text", "NO", "", None), "signed": ("boolean", "NO", "", None),
        "vote_block_id_hash_base64": ("text", "YES", "", None), "vote_block_id_hash_hex": ("text", "YES", "", None), "vote_block_id_parts_total": ("integer", "YES", "", None),
        "vote_block_id_parts_hash_base64": ("text", "YES", "", None), "vote_block_id_parts_hash_hex": ("text", "YES", "", None), "vote_block_id_is_zero": ("boolean", "NO", "", "false"),
        "block_id_matches_commit": ("boolean", "NO", "", "false"), "signature_base64": ("text", "YES", "", None), "raw_precommit": ("jsonb", "YES", "", None),
        "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "rpc_endpoints": {
        "id": ("bigint", "NO", "a", None), "url": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "is_enabled": ("boolean", "NO", "", "true"), "is_selected": ("boolean", "NO", "", "false"),
        "last_checked_at": ("timestamp with time zone", "YES", "", None), "last_selected_at": ("timestamp with time zone", "YES", "", None), "latest_observed_height": ("bigint", "YES", "", None), "observed_lag": ("bigint", "YES", "", None),
        "catching_up": ("boolean", "YES", "", None), "healthy": ("boolean", "YES", "", None), "last_error": ("text", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "rpc_endpoint_checks": {
        "id": ("bigint", "NO", "a", None), "rpc_endpoint_id": ("bigint", "NO", "", None), "checked_at": ("timestamp with time zone", "NO", "", "now()"), "chain_id": ("text", "NO", "", None),
        "latest_observed_height": ("bigint", "YES", "", None), "observed_lag": ("bigint", "YES", "", None), "catching_up": ("boolean", "YES", "", None), "healthy": ("boolean", "NO", "", None),
        "selected_for_cycle": ("boolean", "NO", "", "false"), "switch_reason": ("text", "YES", "", None), "error_message": ("text", "YES", "", None),
    },
    "indexer_state": {
        "state_key": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "last_finalized_height": ("bigint", "NO", "", None), "finalized_tip_height": ("bigint", "YES", "", None), "selected_rpc_endpoint_id": ("bigint", "YES", "", None), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
}
EXPECTED_PRIMARY_KEYS = {"blocks": ("height",), "transactions": ("id",), "validators": ("signing_address",), "validator_set_members": ("height", "signing_address"), "validator_signatures": ("height", "signing_address"), "rpc_endpoints": ("id",), "rpc_endpoint_checks": ("id",), "indexer_state": ("state_key",)}
EXPECTED_UNIQUES = {("blocks", ("block_hash_base64",)), ("blocks", ("block_hash_hex",)), ("transactions", ("block_height", "tx_index")), ("validators", ("public_key_type", "public_key_value")), ("rpc_endpoints", ("url",))}
EXPECTED_FOREIGN_KEYS = {
    ("transactions", ("block_height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("signing_address",), "validators", ("signing_address",), "r"),
    ("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "c"),
    ("rpc_endpoint_checks", ("rpc_endpoint_id",), "rpc_endpoints", ("id",), "c"),
    ("indexer_state", ("selected_rpc_endpoint_id",), "rpc_endpoints", ("id",), "n"),
}
EXPECTED_CHECKS = {
    "blocks_tx_count_check": "check",
    "blocks_block_hash_hex_uppercase": "check ((block_hash_hex = upper(block_hash_hex)))",
    "transactions_tx_index_check": "check",
    "transactions_raw_base64_length_check": "check",
    "transactions_decoded_byte_length_check": "check",
    "transactions_decode_status_check": "check",
    "transactions_raw_base64_length_matches": "check ((raw_base64_length = char_length(raw_base64)))",
    "transactions_decode_status_consistent": "check",
    "validators_first_seen_height_check": "check",
    "validators_last_seen_height_check": "check ((last_seen_height >= first_seen_height))",
    "validator_set_members_voting_power_check": "check ((voting_power >= (0)::numeric))",
    "validator_set_members_validator_index_check": "check",
    "validator_signatures_vote_status_check": "check",
    "validator_signatures_vote_block_id_parts_total_check": "check",
    "validator_signatures_signed_only_matching_commit": "check",
    "validator_signatures_commit_vote_consistent": "check",
    "validator_signatures_nil_vote_consistent": "check",
    "validator_signatures_absent_vote_consistent": "check",
    "validator_signatures_invalid_vote_consistent": "check",
    "validator_signatures_vote_hash_hex_uppercase": "check",
    "validator_signatures_vote_parts_hash_hex_uppercase": "check",
    "rpc_endpoints_latest_observed_height_check": "check",
    "rpc_endpoints_observed_lag_check": "check",
    "rpc_endpoints_no_secret_url": "check",
    "rpc_endpoint_checks_latest_observed_height_check": "check",
    "rpc_endpoint_checks_observed_lag_check": "check",
    "indexer_state_last_finalized_height_check": "check",
    "indexer_state_finalized_tip_height_check": "check",
    "indexer_state_default_key": "check ((state_key = 'default'::text))",
}
EXPECTED_INDEXES = {
    "blocks_time_utc_idx": ("blocks", False, (("time_utc", "DESC"),), None),
    "validator_set_members_height_power_idx": ("validator_set_members", False, (("height", "ASC"), ("voting_power", "DESC"), ("signing_address", "ASC")), None),
    "validator_set_members_signing_height_idx": ("validator_set_members", False, (("signing_address", "ASC"), ("height", "DESC")), None),
    "validator_signatures_signing_height_status_idx": ("validator_signatures", False, (("signing_address", "ASC"), ("height", "DESC"), ("vote_status", "ASC"), ("signed", "ASC")), None),
    "validator_signatures_height_status_idx": ("validator_signatures", False, (("height", "DESC"), ("vote_status", "ASC"), ("signing_address", "ASC")), None),
    "rpc_endpoints_health_idx": ("rpc_endpoints", False, (("chain_id", "ASC"), ("is_enabled", "ASC"), ("healthy", "ASC"), ("latest_observed_height", "DESC")), None),
    "rpc_endpoints_one_selected_per_chain_idx": ("rpc_endpoints", True, (("chain_id", "ASC"),), "is_selected"),
    "rpc_endpoint_checks_endpoint_time_idx": ("rpc_endpoint_checks", False, (("rpc_endpoint_id", "ASC"), ("checked_at", "DESC")), None),
    "rpc_endpoint_checks_chain_selected_time_idx": ("rpc_endpoint_checks", False, (("chain_id", "ASC"), ("selected_for_cycle", "ASC"), ("checked_at", "DESC")), None),
}

class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing schema is not compatible with the expected v0.4 schema."""


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.strip()).lower()


def _default_matches(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return actual is None
    return _norm(actual) == expected or (expected == "now()" and _norm(actual) == "now()")


def validate_schema_snapshot(snapshot: dict[str, Any]) -> None:
    tables = set(snapshot.get("tables", set()))
    if tables != EXPECTED_TABLES:
        missing = EXPECTED_TABLES - tables
        extra = tables - EXPECTED_TABLES
        details = []
        if missing:
            details.append(f"missing expected tables: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected public tables: {', '.join(sorted(extra))}")
        raise SchemaCompatibilityError("; ".join(details))
    for table, expected_columns in EXPECTED_COLUMNS.items():
        actual_columns = snapshot.get("columns", {}).get(table, {})
        if set(actual_columns) != set(expected_columns):
            raise SchemaCompatibilityError(f"incompatible column set for {table}")
        for column, expected in expected_columns.items():
            actual = tuple(actual_columns[column])
            if actual[:3] != expected[:3] or not _default_matches(actual[3], expected[3]):
                raise SchemaCompatibilityError(f"incompatible column {table}.{column}")
    for table, columns in EXPECTED_PRIMARY_KEYS.items():
        if tuple(snapshot.get("primary_keys", {}).get(table, ())) != columns:
            raise SchemaCompatibilityError(f"incompatible primary key for {table}")
    if EXPECTED_UNIQUES != {(table, tuple(cols)) for table, cols in snapshot.get("unique_constraints", set())}:
        raise SchemaCompatibilityError("incompatible unique constraints")
    if EXPECTED_FOREIGN_KEYS != {(table, tuple(cols), ref, tuple(ref_cols), action) for table, cols, ref, ref_cols, action in snapshot.get("foreign_keys", set())}:
        raise SchemaCompatibilityError("incompatible foreign keys")
    checks = snapshot.get("check_constraints", {})
    if set(checks) != set(EXPECTED_CHECKS):
        raise SchemaCompatibilityError("incompatible check constraint set")
    for name, expected in EXPECTED_CHECKS.items():
        actual = _norm(checks[name]) or ""
        if expected != "check" and actual != expected:
            raise SchemaCompatibilityError(f"incompatible check constraint {name}")
        if expected == "check" and not actual.startswith("check"):
            raise SchemaCompatibilityError(f"incompatible check constraint {name}")
    indexes = snapshot.get("indexes", {})
    if set(indexes) != set(EXPECTED_INDEXES):
        raise SchemaCompatibilityError("incompatible explicit index set")
    for name, expected in EXPECTED_INDEXES.items():
        actual = indexes[name]
        if (actual[0], bool(actual[1]), tuple(actual[2]), _norm(actual[3])) != (expected[0], expected[1], expected[2], _norm(expected[3])):
            raise SchemaCompatibilityError(f"incompatible index {name}")


def fetch_schema_snapshot(cursor) -> dict[str, Any]:
    cursor.execute("""
        SELECT c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
    """)
    tables = {row[0] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT c.relname, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod),
               CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END,
               a.attidentity,
               pg_catalog.pg_get_expr(d.adbin, d.adrelid)
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    """)
    columns: dict[str, dict[str, tuple[str, str, str, str | None]]] = {}
    for table, column, data_type, nullable, identity, default in cursor.fetchall():
        columns.setdefault(table, {})[column] = (data_type, nullable, identity or "", default)

    cursor.execute("""
        SELECT con.oid, rel.relname, con.contype, con.conname,
               COALESCE(local_cols.columns, ARRAY[]::text[]), ref_rel.relname,
               COALESCE(ref_cols.columns, ARRAY[]::text[]), con.confdeltype,
               pg_catalog.pg_get_constraintdef(con.oid)
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class rel ON rel.oid = con.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = rel.relnamespace
        LEFT JOIN pg_catalog.pg_class ref_rel ON ref_rel.oid = con.confrelid
        LEFT JOIN LATERAL (
            SELECT array_agg(att.attname ORDER BY keys.ord) AS columns
            FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ord)
            JOIN pg_catalog.pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = keys.attnum
        ) local_cols ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(att.attname ORDER BY keys.ord) AS columns
            FROM unnest(con.confkey) WITH ORDINALITY AS keys(attnum, ord)
            JOIN pg_catalog.pg_attribute att ON att.attrelid = con.confrelid AND att.attnum = keys.attnum
        ) ref_cols ON true
        WHERE n.nspname = 'public' AND rel.relkind = 'r'
        ORDER BY rel.relname, con.oid
    """)
    primary: dict[str, tuple[str, ...]] = {}
    uniques: set[tuple[str, tuple[str, ...]]] = set()
    foreign_keys: set[tuple[str, tuple[str, ...], str, tuple[str, ...], str]] = set()
    checks: dict[str, str] = {}
    for _oid, table, contype, name, local_cols, ref_table, ref_cols, delete_action, definition in cursor.fetchall():
        local_tuple = tuple(local_cols or ())
        if contype == "p":
            primary[table] = local_tuple
        elif contype == "u":
            uniques.add((table, local_tuple))
        elif contype == "f":
            foreign_keys.add((table, local_tuple, ref_table, tuple(ref_cols or ()), delete_action))
        elif contype == "c":
            checks[name] = _norm(definition) or ""

    cursor.execute("""
        SELECT idx.relname, tbl.relname, i.indisunique,
               array_agg(att.attname ORDER BY keys.ord),
               array_agg(CASE WHEN (i.indoption[keys.ord - 1] & 1) = 1 THEN 'DESC' ELSE 'ASC' END ORDER BY keys.ord),
               pg_catalog.pg_get_expr(i.indpred, i.indrelid)
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_catalog.pg_class tbl ON tbl.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = tbl.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ord) ON keys.attnum <> 0
        JOIN pg_catalog.pg_attribute att ON att.attrelid = tbl.oid AND att.attnum = keys.attnum
        WHERE n.nspname = 'public' AND NOT i.indisprimary AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_constraint con WHERE con.conindid = i.indexrelid AND con.contype IN ('u', 'p')
        )
        GROUP BY idx.relname, tbl.relname, i.indisunique, i.indpred, i.indrelid
        ORDER BY idx.relname
    """)
    indexes = {}
    for name, table, unique, cols, directions, predicate in cursor.fetchall():
        indexes[name] = (table, bool(unique), tuple(zip(cols, directions)), predicate)
    return {"tables": tables, "columns": columns, "primary_keys": primary, "unique_constraints": uniques, "foreign_keys": foreign_keys, "check_constraints": checks, "indexes": indexes}


def initialize_or_validate(database_url: str, schema_path: Path = SCHEMA, connect=None) -> None:
    if not database_url:
        raise ValueError("DATABASE_URL is required; value is intentionally not printed")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    schema_sql = schema_path.read_text()
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.relname FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
            """)
            existing = {row[0] for row in cursor.fetchall()}
            if not existing:
                cursor.execute(schema_sql)
                validate_schema_snapshot(fetch_schema_snapshot(cursor))
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
