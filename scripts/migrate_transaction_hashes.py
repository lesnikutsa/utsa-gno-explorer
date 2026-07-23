#!/usr/bin/env python3
"""Backfill canonical transaction hashes; run only while the indexer is stopped."""
from __future__ import annotations

import argparse
import copy
import hashlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.init_database import EXPECTED_CHECKS, EXPECTED_COLUMNS, EXPECTED_INDEXES, fetch_schema_snapshot, validate_schema_snapshot

MIGRATION = REPO_ROOT / "database" / "migrations" / "0002_add_transaction_hash.sql"
HASH_COLUMN = "tx_hash_hex"
HASH_CONSTRAINTS = {"transactions_tx_hash_hex_format", "transactions_tx_hash_consistent"}
HASH_INDEX = "transactions_tx_hash_hex_idx"


class MigrationPreconditionError(RuntimeError):
    """Raised when the catalog is neither exact legacy nor fully compatible."""


def _validate_exact_legacy(cursor) -> None:
    """Validate all legacy objects by augmenting its snapshot to the final shape."""
    snapshot = copy.deepcopy(fetch_schema_snapshot(cursor))
    transaction_columns = snapshot.get("columns", {}).get("transactions", {})
    if HASH_COLUMN in transaction_columns:
        raise MigrationPreconditionError("transaction hash schema is an unknown partial state")
    transaction_columns[HASH_COLUMN] = EXPECTED_COLUMNS["transactions"][HASH_COLUMN]
    checks = snapshot.setdefault("check_constraints", {})
    for name in HASH_CONSTRAINTS:
        if name in checks:
            raise MigrationPreconditionError("transaction hash schema is an unknown partial state")
        checks[name] = EXPECTED_CHECKS[name]
    indexes = snapshot.setdefault("indexes", {})
    if HASH_INDEX in indexes:
        raise MigrationPreconditionError("transaction hash schema is an unknown partial state")
    indexes[HASH_INDEX] = EXPECTED_INDEXES[HASH_INDEX]
    try:
        validate_schema_snapshot(snapshot)
    except Exception as exc:
        raise MigrationPreconditionError("public schema is not the exact legacy schema") from exc


def _catalog_state(cursor) -> str:
    cursor.execute("SELECT to_regclass('public.transactions')")
    if cursor.fetchone()[0] is None:
        cursor.execute("SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
        if cursor.fetchone()[0] == 0:
            return "empty"
        return "unknown"
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'transactions'
          AND column_name = 'tx_hash_hex'
    """)
    has_column = cursor.fetchone() is not None
    cursor.execute("""
        SELECT conname, convalidated FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.transactions'::regclass
          AND conname IN ('transactions_tx_hash_hex_format', 'transactions_tx_hash_consistent')
    """)
    constraints = {name: validated for name, validated in cursor.fetchall()}
    cursor.execute("""
        SELECT idx.relname, i.indisunique, pg_catalog.pg_get_expr(i.indpred, i.indrelid)
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = idx.relnamespace
        WHERE n.nspname = 'public'
          AND idx.relname IN ('transactions_tx_hash_hex_idx', 'transactions_tx_hash_hex_unique')
    """)
    hash_indexes = cursor.fetchall()
    has_correct_index = (
        len(hash_indexes) == 1
        and hash_indexes[0][0] == HASH_INDEX
        and hash_indexes[0][1] is False
        and str(hash_indexes[0][2]).strip().strip("()") == "tx_hash_hex IS NOT NULL"
    )
    if not has_column and not constraints and not hash_indexes:
        return "legacy"
    if has_column and constraints == {name: True for name in HASH_CONSTRAINTS} and has_correct_index:
        return "compatible"
    return "unknown"


def _backfill(cursor, batch_size: int) -> None:
    last_id = 0
    while True:
        cursor.execute("""
            SELECT id, decoded_bytes FROM transactions
            WHERE decode_status = 'decoded' AND tx_hash_hex IS NULL AND id > %s
            ORDER BY id LIMIT %s
        """, (last_id, batch_size))
        rows = cursor.fetchall()
        if not rows:
            break
        updates = []
        for row_id, decoded_bytes in rows:
            tx_hash = hashlib.sha256(bytes(decoded_bytes)).hexdigest().upper()
            updates.append((tx_hash, row_id))
            last_id = row_id
        cursor.executemany("UPDATE transactions SET tx_hash_hex = %s WHERE id = %s", updates)


def _verify(cursor) -> None:
    checks = (
        "decode_status = 'decoded' AND tx_hash_hex IS NULL",
        "decode_status IN ('invalid_base64', 'not_attempted') AND tx_hash_hex IS NOT NULL",
        "tx_hash_hex IS NOT NULL AND tx_hash_hex !~ '^[0-9A-F]{64}$'",
    )
    for condition in checks:
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM transactions WHERE {condition})")
        if cursor.fetchone()[0]:
            raise MigrationPreconditionError("transaction hash backfill verification failed")


def _verify_hash_contents(cursor, batch_size: int) -> None:
    """Verify every stored decoded hash against its exact decoded bytes."""
    last_id = 0
    while True:
        cursor.execute("""
            SELECT id, decoded_bytes, tx_hash_hex FROM transactions
            WHERE decode_status = 'decoded' AND id > %s
            ORDER BY id LIMIT %s
        """, (last_id, batch_size))
        rows = cursor.fetchall()
        if not rows:
            return
        for row_id, decoded_bytes, stored_hash in rows:
            expected_hash = hashlib.sha256(bytes(decoded_bytes)).hexdigest().upper()
            if stored_hash != expected_hash:
                raise MigrationPreconditionError("stored transaction hash verification failed")
            last_id = row_id


def migrate_transaction_hashes(database_url: str, migration_path: Path = MIGRATION,
                               batch_size: int = 500, connect=None) -> str:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            state = _catalog_state(cursor)
            if state == "empty":
                raise MigrationPreconditionError("empty public schema; use python scripts/init_database.py")
            if state == "unknown":
                raise MigrationPreconditionError("transaction hash schema is an unknown partial state")
            if state == "compatible":
                validate_schema_snapshot(fetch_schema_snapshot(cursor))
                _verify_hash_contents(cursor, batch_size)
                return "already-compatible"
            _validate_exact_legacy(cursor)
            cursor.execute(migration_path.read_text())
            _backfill(cursor, batch_size)
            _verify(cursor)
            _verify_hash_contents(cursor, batch_size)
            cursor.execute("ALTER TABLE transactions VALIDATE CONSTRAINT transactions_tx_hash_hex_format")
            cursor.execute("ALTER TABLE transactions VALIDATE CONSTRAINT transactions_tx_hash_consistent")
            cursor.execute("CREATE INDEX transactions_tx_hash_hex_idx ON transactions(tx_hash_hex) WHERE tx_hash_hex IS NOT NULL")
            validate_schema_snapshot(fetch_schema_snapshot(cursor))
        connection.commit()
    return "applied"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", default=str(MIGRATION))
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        result = migrate_transaction_hashes(os.environ.get("DATABASE_URL", ""), Path(args.migration), args.batch_size)
    except Exception:
        print("Transaction hash migration failed; ensure the indexer is stopped and inspect the database catalog", file=sys.stderr)
        return 1
    print("Transaction hash schema is already compatible" if result == "already-compatible" else "Transaction hash migration applied and validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
