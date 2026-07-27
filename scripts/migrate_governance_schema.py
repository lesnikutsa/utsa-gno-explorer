#!/usr/bin/env python3
"""Explicitly apply additive governance persistence migration 0004."""
from __future__ import annotations
import os, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from scripts.init_database import (FINAL_SCHEMA_EXPECTATIONS, PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
    fetch_schema_snapshot, validate_schema_snapshot, validate_schema_stage)
MIGRATION=ROOT/"database/migrations/0004_add_governance_persistence.sql"
TABLES={"governance_proposals","governance_votes","governance_sync_state"}

def migrate(database_url:str,connect=None):
    if not database_url: raise ValueError("DATABASE_URL is required")
    if connect is None:
        import psycopg
        connect=psycopg.connect
    with connect(database_url) as connection, connection.cursor() as cursor:
        snapshot=fetch_schema_snapshot(cursor); present=snapshot.get("tables",set()) & TABLES
        if present and present != TABLES: raise RuntimeError("unknown partial governance schema")
        if not present:
            if not snapshot.get("tables"): raise RuntimeError("empty public schema; use python scripts/init_database.py")
            validate_schema_stage(snapshot,PRE_GOVERNANCE_SCHEMA_EXPECTATIONS)
            cursor.execute(MIGRATION.read_text())
        validate_schema_snapshot(fetch_schema_snapshot(cursor),FINAL_SCHEMA_EXPECTATIONS)
        connection.commit()
    return "applied" if not present else "already-compatible"

def _safe(message,url):
    message=message.replace(url,"[redacted DATABASE_URL]") if url else message
    return re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@",r"\1[redacted]@",message)
def main():
    url=os.getenv("DATABASE_URL","")
    try: action=migrate(url)
    except Exception as exc:
        print(f"Governance migration failed: {_safe(str(exc),url)}",file=sys.stderr); return 1
    print(f"Governance migration succeeded: {action}"); return 0
if __name__=="__main__": raise SystemExit(main())
