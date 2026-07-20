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
    "blocks", "transactions", "validators", "validator_set_members", "validator_signatures", "rpc_endpoints", "rpc_endpoint_checks", "indexer_state", "valoper_profiles", "valopers_snapshot_state",
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
    "valoper_profiles": {
        "operator_address": ("text", "NO", "", None), "moniker": ("text", "NO", "", None), "description": ("text", "NO", "", None), "server_type": ("text", "NO", "", None), "signing_address": ("text", "NO", "", None), "signing_pubkey": ("text", "NO", "", None), "source_height": ("bigint", "NO", "", None), "list_position": ("integer", "NO", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "valopers_snapshot_state": {
        "state_key": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "source_height": ("bigint", "NO", "", None), "page_count": ("integer", "NO", "", None), "profile_count": ("integer", "NO", "", None), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
}
EXPECTED_PRIMARY_KEYS = {"blocks": ("height",), "transactions": ("id",), "validators": ("signing_address",), "validator_set_members": ("height", "signing_address"), "validator_signatures": ("height", "signing_address"), "rpc_endpoints": ("id",), "rpc_endpoint_checks": ("id",), "indexer_state": ("state_key",), "valoper_profiles": ("operator_address",), "valopers_snapshot_state": ("state_key",)}
EXPECTED_UNIQUES = {("blocks", ("block_hash_base64",)), ("blocks", ("block_hash_hex",)), ("transactions", ("block_height", "tx_index")), ("validators", ("public_key_type", "public_key_value")), ("rpc_endpoints", ("url",)), ("valoper_profiles", ("signing_address",)), ("valoper_profiles", ("signing_pubkey",))}
EXPECTED_FOREIGN_KEYS = {
    ("transactions", ("block_height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("signing_address",), "validators", ("signing_address",), "r"),
    ("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "c"),
    ("rpc_endpoint_checks", ("rpc_endpoint_id",), "rpc_endpoints", ("id",), "c"),
    ("indexer_state", ("selected_rpc_endpoint_id",), "rpc_endpoints", ("id",), "n"),
}
EXPECTED_CHECKS = {
    "blocks_tx_count_check": "CHECK (tx_count >= 0)",
    "blocks_block_hash_hex_uppercase": "CHECK (block_hash_hex = upper(block_hash_hex))",
    "transactions_tx_index_check": "CHECK (tx_index >= 0)",
    "transactions_raw_base64_length_check": "CHECK (raw_base64_length >= 0)",
    "transactions_decoded_byte_length_check": "CHECK (decoded_byte_length IS NULL OR decoded_byte_length >= 0)",
    "transactions_decode_status_check": "CHECK (decode_status IN ('decoded', 'invalid_base64', 'not_attempted'))",
    "transactions_raw_base64_length_matches": "CHECK (raw_base64_length = char_length(raw_base64))",
    "transactions_decode_status_consistent": "CHECK ((decode_status = 'decoded' AND decoded_bytes IS NOT NULL AND decoded_byte_length = octet_length(decoded_bytes)) OR (decode_status IN ('invalid_base64', 'not_attempted') AND decoded_bytes IS NULL AND decoded_byte_length IS NULL))",
    "validators_first_seen_height_check": "CHECK (first_seen_height >= 0)",
    "validators_last_seen_height_check": "CHECK (last_seen_height >= first_seen_height)",
    "validator_set_members_voting_power_check": "CHECK (voting_power >= 0)",
    "validator_set_members_validator_index_check": "CHECK (validator_index IS NULL OR validator_index >= 0)",
    "validator_signatures_vote_status_check": "CHECK (vote_status IN ('commit', 'nil', 'absent', 'invalid'))",
    "validator_signatures_vote_block_id_parts_total_check": "CHECK (vote_block_id_parts_total IS NULL OR vote_block_id_parts_total >= 0)",
    "validator_signatures_signed_only_matching_commit": "CHECK (signed = (vote_status = 'commit' AND block_id_matches_commit))",
    "validator_signatures_commit_vote_consistent": "CHECK (vote_status <> 'commit' OR (block_id_matches_commit AND NOT vote_block_id_is_zero AND vote_block_id_hash_base64 IS NOT NULL AND vote_block_id_hash_hex IS NOT NULL AND vote_block_id_parts_total IS NOT NULL AND vote_block_id_parts_hash_base64 IS NOT NULL AND vote_block_id_parts_hash_hex IS NOT NULL AND signature_base64 IS NOT NULL))",
    "validator_signatures_nil_vote_consistent": "CHECK (vote_status <> 'nil' OR (NOT signed AND vote_block_id_is_zero AND NOT block_id_matches_commit))",
    "validator_signatures_absent_vote_consistent": "CHECK (vote_status <> 'absent' OR (NOT signed AND NOT vote_block_id_is_zero AND NOT block_id_matches_commit AND vote_block_id_hash_base64 IS NULL AND vote_block_id_hash_hex IS NULL AND vote_block_id_parts_total IS NULL AND vote_block_id_parts_hash_base64 IS NULL AND vote_block_id_parts_hash_hex IS NULL AND signature_base64 IS NULL AND raw_precommit IS NULL))",
    "validator_signatures_invalid_vote_consistent": "CHECK (vote_status <> 'invalid' OR (NOT signed AND NOT block_id_matches_commit))",
    "validator_signatures_vote_hash_hex_uppercase": "CHECK (vote_block_id_hash_hex IS NULL OR vote_block_id_hash_hex = upper(vote_block_id_hash_hex))",
    "validator_signatures_vote_parts_hash_hex_uppercase": "CHECK (vote_block_id_parts_hash_hex IS NULL OR vote_block_id_parts_hash_hex = upper(vote_block_id_parts_hash_hex))",
    "rpc_endpoints_latest_observed_height_check": "CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0)",
    "rpc_endpoints_observed_lag_check": "CHECK (observed_lag IS NULL OR observed_lag >= 0)",
    "rpc_endpoints_no_secret_url": "CHECK (url !~* '(password|token|apikey|api_key|secret)=')",
    "rpc_endpoint_checks_latest_observed_height_check": "CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0)",
    "rpc_endpoint_checks_observed_lag_check": "CHECK (observed_lag IS NULL OR observed_lag >= 0)",
    "indexer_state_last_finalized_height_check": "CHECK (last_finalized_height >= 0)",
    "indexer_state_finalized_tip_height_check": "CHECK (finalized_tip_height IS NULL OR finalized_tip_height >= last_finalized_height)",
    "indexer_state_default_key": "CHECK (state_key = 'default')",
    "valoper_profiles_source_height_check": "CHECK (source_height >= 1)",
    "valoper_profiles_list_position_check": "CHECK (list_position >= 0)",
    "valoper_profiles_moniker_length_check": "CHECK (char_length(moniker) >= 1 AND char_length(moniker) <= 32)",
    "valoper_profiles_description_length_check": "CHECK (octet_length(description) >= 1 AND octet_length(description) <= 2048)",
    "valoper_profiles_server_type_check": "CHECK (server_type IN ('cloud', 'on-prem', 'data-center'))",
    "valoper_profiles_operator_address_check": "CHECK (operator_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')",
    "valoper_profiles_signing_address_check": "CHECK (signing_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')",
    "valoper_profiles_signing_pubkey_check": "CHECK (signing_pubkey ~ '^gpub1[023456789acdefghjklmnpqrstuvwxyz]+$' AND (octet_length(signing_pubkey) >= 91 AND octet_length(signing_pubkey) <= 256))",
    "valopers_snapshot_state_default_key": "CHECK (state_key = 'default')",
    "valopers_snapshot_state_source_height_check": "CHECK (source_height >= 1)",
    "valopers_snapshot_state_page_count_check": "CHECK (page_count >= 0 AND page_count <= 20)",
    "valopers_snapshot_state_profile_count_check": "CHECK (profile_count >= 0 AND profile_count <= 1000)",
    "valopers_snapshot_state_counts_consistent": "CHECK ((profile_count = 0 AND page_count = 0) OR (profile_count > 0 AND page_count >= 1))",
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
    "valoper_profiles_list_position_idx": ("valoper_profiles", False, (("list_position", "ASC"), ("operator_address", "ASC")), None),
    "valoper_profiles_moniker_idx": ("valoper_profiles", False, (("moniker", "ASC"), ("operator_address", "ASC")), None),
}

class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing schema is not compatible with the expected explorer schema."""


def _is_wrapped(value: str) -> bool:
    if not (value.startswith("(") and value.endswith(")")):
        return False
    depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(value) - 1:
                return False
    return depth == 0


def _strip_outer_parentheses(value: str) -> str:
    while _is_wrapped(value):
        value = value[1:-1].strip()
    return value


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _find_matching_parenthesis(value: str, start: int) -> int | None:
    depth = 0
    in_quote = False
    index = start
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return None


def _has_top_level_boolean_operator(value: str) -> bool:
    in_quote = False
    depth = 0
    index = 0
    lowered = value.lower()
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif depth == 0:
                if lowered.startswith("and", index) or lowered.startswith("or", index):
                    before = lowered[index - 1] if index > 0 else " "
                    after_index = index + (3 if lowered.startswith("and", index) else 2)
                    after = lowered[after_index] if after_index < len(value) else " "
                    if not _is_identifier_char(before) and not _is_identifier_char(after):
                        return True
        index += 1
    return False


def _has_top_level_comma(value: str) -> bool:
    in_quote = False
    depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                return True
        index += 1
    return False


def _can_remove_parentheses(value: str, start: int, end: int) -> bool:
    before_index = start - 1
    while before_index >= 0 and value[before_index].isspace():
        before_index -= 1
    if before_index >= 0 and _is_identifier_char(value[before_index]):
        token_end = before_index + 1
        token_start = before_index
        while token_start >= 0 and _is_identifier_char(value[token_start]):
            token_start -= 1
        previous_token = value[token_start + 1:token_end].lower()
        if previous_token not in {"and", "or", "not", "in"}:
            return False
    inner = value[start + 1:end].strip()
    if not inner:
        return False
    if _has_top_level_comma(inner):
        return False
    if _has_top_level_boolean_operator(inner):
        return False
    return True


def _remove_atomic_parentheses(value: str) -> str:
    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(value):
            if value[index] != "(":
                index += 1
                continue
            end = _find_matching_parenthesis(value, index)
            if end is None:
                break
            if _can_remove_parentheses(value, index, end):
                value = value[:index] + value[index + 1:end] + value[end + 1:]
                changed = True
                break
            index += 1
    return value

def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized.startswith("check"):
        normalized = normalized[5:].strip()
    normalized = re.sub(r"\((\d+)\)::(?:text|numeric|bigint|integer|boolean)", r"\1", normalized)
    normalized = re.sub(r"::(?:text|numeric|bigint|integer|boolean)", "", normalized)
    normalized = re.sub(r"([a-z_]+) = any \(array\[(.*?)\]\)", r"\1 in (\2)", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _strip_outer_parentheses(normalized)
    normalized = _remove_atomic_parentheses(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


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
    actual_uniques = {(table, tuple(cols)) for table, cols in snapshot.get("unique_constraints", set())}
    if EXPECTED_UNIQUES != actual_uniques:
        raise SchemaCompatibilityError(f"incompatible unique constraints: missing={sorted(EXPECTED_UNIQUES - actual_uniques)} unexpected={sorted(actual_uniques - EXPECTED_UNIQUES)}")
    actual_foreign_keys = {(table, tuple(cols), ref, tuple(ref_cols), action) for table, cols, ref, ref_cols, action in snapshot.get("foreign_keys", set())}
    if EXPECTED_FOREIGN_KEYS != actual_foreign_keys:
        raise SchemaCompatibilityError(f"incompatible foreign keys: missing={sorted(EXPECTED_FOREIGN_KEYS - actual_foreign_keys)} unexpected={sorted(actual_foreign_keys - EXPECTED_FOREIGN_KEYS)}")
    checks = snapshot.get("check_constraints", {})
    actual_check_names = set(checks)
    expected_check_names = set(EXPECTED_CHECKS)
    if actual_check_names != expected_check_names:
        raise SchemaCompatibilityError(f"incompatible check constraint set: missing={sorted(expected_check_names - actual_check_names)} unexpected={sorted(actual_check_names - expected_check_names)}")
    for name, expected in EXPECTED_CHECKS.items():
        actual = _norm(checks[name]) or ""
        expected_normalized = _norm(expected) or ""
        if actual != expected_normalized:
            raise SchemaCompatibilityError(f"incompatible check constraint {name}: expected={expected_normalized!r} actual={actual!r}")
    indexes = snapshot.get("indexes", {})
    actual_index_names = set(indexes)
    expected_index_names = set(EXPECTED_INDEXES)
    if actual_index_names != expected_index_names:
        raise SchemaCompatibilityError(f"incompatible explicit index set: missing={sorted(expected_index_names - actual_index_names)} unexpected={sorted(actual_index_names - expected_index_names)}")
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
               CASE
                   WHEN con.contype = 'c' THEN pg_catalog.pg_get_expr(con.conbin, con.conrelid)
                   ELSE pg_catalog.pg_get_constraintdef(con.oid)
               END
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
