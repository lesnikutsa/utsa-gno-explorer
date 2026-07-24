#!/usr/bin/env python3
"""Explicitly apply additive network-distribution schema migration 0003."""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.init_database import EXPECTED_COLUMNS, fetch_schema_snapshot, validate_schema_snapshot
MIGRATION = ROOT / "database/migrations/0003_add_network_distribution.sql"
TABLES = {"network_distribution_geo_cache", "network_distribution_snapshots", "network_distribution_snapshot_sources"}

def migrate(database_url: str, connect=None):
    if not database_url: raise ValueError("DATABASE_URL is required")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' AND tablename = ANY(%s)", (list(TABLES),))
        present = {row[0] for row in cursor.fetchall()}
        if present and present != TABLES:
            raise RuntimeError(f"unknown partial network-distribution schema: {sorted(present)}")
        if not present:
            cursor.execute(MIGRATION.read_text())
        validate_schema_snapshot(fetch_schema_snapshot(cursor))
        connection.commit()

def main():
    try: migrate(os.getenv("DATABASE_URL", ""))
    except Exception as exc:
        print(f"Network-distribution migration failed: {exc}", file=sys.stderr); return 1
    print("Network-distribution migration succeeded"); return 0
if __name__ == "__main__": raise SystemExit(main())
