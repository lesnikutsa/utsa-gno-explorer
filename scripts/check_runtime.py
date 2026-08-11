#!/usr/bin/env python3
"""Perform a compact, strictly read-only production runtime inspection."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from indexer.config import load_config
from indexer.database import PostgresDatabase
from scripts.check_realm_call_index_coverage import coverage_is_contiguous

SERVICES = (
    "utsa-gno-api.service", "utsa-gno-indexer.service",
    "utsa-gno-governance-updater.service",
)
TIMERS = (
    "utsa-gno-realm-catalog-refresh.timer",
    "utsa-gno-realm-metadata-refresh.timer",
    "utsa-gno-valopers-refresh.timer",
    "utsa-gno-network-distribution.timer",
)
SCHEDULED_SERVICES = (
    "utsa-gno-realm-catalog-refresh.service",
    "utsa-gno-realm-metadata-refresh.service",
    "utsa-gno-valopers-refresh.service",
    "utsa-gno-network-distribution.service",
)
HEALTH_URL = "http://127.0.0.1:18180/api/health"


@dataclass(frozen=True)
class DatabaseSnapshot:
    indexed_height: int | None
    catalog_state: tuple[int, int] | None
    catalog_counts: tuple[int, int, int]
    call_state: tuple[int, int] | None
    call_rows: int
    metadata_rows: int
    metadata_statuses: tuple[tuple[str, int], ...]
    metadata_height: int | None
    metadata_refresh: tuple[int, str] | None


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def line(self, level: str, message: str) -> None:
        if level == "FAIL": self.failures += 1
        if level == "WARN": self.warnings += 1
        print(f"[{level}]".ljust(7) + message)


def inspect_unit(unit: str) -> dict[str, str]:
    result = subprocess.run(
        ["systemctl", "show", unit, "--property=LoadState,ActiveState,UnitFileState"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("systemctl inspection failed")
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def inspect_database(database_url: str, chain_id: str) -> DatabaseSnapshot:
    database = PostgresDatabase(database_url)
    with database.connect() as connection, connection.transaction():
        with connection.cursor() as cursor:
            # PostgreSQL must establish these characteristics before the first snapshot.
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute(
                "SELECT current_setting('transaction_read_only'), "
                "current_setting('transaction_isolation')"
            )
            if cursor.fetchone() != ("on", "repeatable read"):
                raise RuntimeError("read-only repeatable-read snapshot unavailable")
            def one(sql: str):
                cursor.execute(sql, (chain_id,))
                return cursor.fetchone()
            indexed = one("SELECT last_finalized_height FROM indexer_state WHERE state_key='default' AND chain_id=%s")
            catalog = one("SELECT observed_height,rpc_path_count FROM realm_catalog_state WHERE chain_id=%s")
            counts = one("SELECT count(*) FILTER (WHERE path_kind='realm'),count(*) FILTER (WHERE path_kind='package'),count(*) FILTER (WHERE rpc_visible) FROM realm_catalog WHERE chain_id=%s")
            call_state = one("SELECT from_height,through_height FROM realm_call_index_state WHERE chain_id=%s")
            call_rows = one("SELECT count(*) FROM realm_call_index WHERE chain_id=%s")
            cursor.execute("SELECT collection_status,count(*) FROM realm_metadata WHERE chain_id=%s GROUP BY collection_status ORDER BY collection_status", (chain_id,))
            statuses = tuple((str(row[0]), int(row[1])) for row in cursor.fetchall())
            metadata = one("SELECT count(*),max(observed_height) FROM realm_metadata WHERE chain_id=%s")
            refresh = one("SELECT observed_height,run_status FROM realm_metadata_refresh_state WHERE chain_id=%s")
    return DatabaseSnapshot(
        int(indexed[0]) if indexed else None,
        (int(catalog[0]), int(catalog[1])) if catalog else None,
        tuple(int(value) for value in (counts or (0, 0, 0))),
        (int(call_state[0]), int(call_state[1])) if call_state else None,
        int(call_rows[0]), int(metadata[0]), statuses,
        int(metadata[1]) if metadata and metadata[1] is not None else None,
        (int(refresh[0]), str(refresh[1])) if refresh else None,
    )


def inspect_api() -> dict[str, object]:
    request = Request(HEALTH_URL, headers={"Accept": "application/json"})
    with urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP status {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("invalid JSON response")
    return payload


def _safe_failure(exc: Exception) -> str:
    """Return only an exception class, never credential-bearing exception text."""
    return type(exc).__name__


def run(
    *, config_loader=load_config, unit_inspector=inspect_unit,
    database_inspector=inspect_database, api_inspector=inspect_api,
) -> int:
    print("UTSA Gno Explorer Runtime Check")
    try:
        config = config_loader()
        if not config.database_url or not config.chain_id:
            raise ValueError("missing required configuration")
    except Exception as exc:
        print(f"[FAIL] Configuration unavailable ({_safe_failure(exc)})")
        print("Result: INSPECTION ERROR\nFailures: 1\nWarnings: 0")
        return 2
    print(f"Chain: {config.chain_id}")
    report = Report()

    print("\nCore services")
    for unit in SERVICES:
        try:
            state = unit_inspector(unit)
            if state.get("LoadState") == "not-found": report.line("FAIL", f"{unit}: not installed")
            elif state.get("ActiveState") == "active": report.line("OK", f"{unit}: active")
            else: report.line("FAIL", f"{unit}: {state.get('ActiveState', 'unknown')}")
        except Exception as exc:
            report.line("FAIL", f"{unit}: inspection unavailable ({_safe_failure(exc)})")

    print("\nScheduled job services")
    for unit in SCHEDULED_SERVICES:
        try:
            state = unit_inspector(unit)
            if state.get("LoadState") == "not-found":
                report.line("FAIL", f"{unit}: not installed")
            elif state.get("LoadState") == "loaded":
                report.line("OK", f"{unit}: installed, {state.get('ActiveState', 'unknown')}")
            else:
                report.line("FAIL", f"{unit}: not loadable ({state.get('LoadState', 'unknown')})")
        except Exception as exc:
            report.line("FAIL", f"{unit}: inspection unavailable ({_safe_failure(exc)})")

    print("\nScheduled job timers")
    for unit in TIMERS:
        try:
            state = unit_inspector(unit)
            enabled, active = state.get("UnitFileState") == "enabled", state.get("ActiveState") == "active"
            if state.get("LoadState") == "not-found": report.line("FAIL", f"{unit}: not installed")
            elif enabled and active: report.line("OK", f"{unit}: enabled, active")
            else: report.line("FAIL", f"{unit}: {'enabled' if enabled else 'disabled'}, {'active' if active else 'inactive'}")
        except Exception as exc:
            report.line("FAIL", f"{unit}: inspection unavailable ({_safe_failure(exc)})")

    print("\nDatabase")
    snapshot = None
    try:
        snapshot = database_inspector(config.database_url, config.chain_id)
        report.line("OK", "PostgreSQL reachable")
        if snapshot.indexed_height is None: report.line("WARN", "Indexed height: no checkpoint yet (fresh database)")
        else: report.line("OK", f"Indexed height: #{snapshot.indexed_height}")
    except Exception as exc:
        report.line("FAIL", f"PostgreSQL inspection unavailable ({_safe_failure(exc)})")

    print("\nRealm derived data")
    if snapshot is not None:
        if snapshot.catalog_state:
            realms, packages, visible = snapshot.catalog_counts
            report.line("OK", f"Catalog: {realms} realms / {packages} packages / {visible} RPC visible; observed #{snapshot.catalog_state[0]}")
        else: report.line("FAIL" if snapshot.indexed_height is not None else "WARN", "Catalog snapshot is missing")
        if snapshot.call_state is None:
            if snapshot.indexed_height is None and snapshot.call_rows == 0:
                report.line("WARN", "Call coverage awaits the first successfully indexed block")
            else:
                report.line("FAIL", "Realm call coverage state is missing for an existing indexed database")
                print("       Recent Calls and Applications cannot claim complete history.\n       Inspect with:\n       .venv/bin/python scripts/check_realm_call_index_coverage.py")
        elif coverage_is_contiguous(snapshot.call_state, snapshot.indexed_height):
            report.line("OK", f"Call coverage: #{snapshot.call_state[0]} -> #{snapshot.call_state[1]}, contiguous ({snapshot.call_rows} rows)")
        else: report.line("FAIL", f"Call coverage is not contiguous at indexed checkpoint #{snapshot.indexed_height}")
        status = ", ".join(f"{name}={count}" for name, count in snapshot.metadata_statuses) or "none"
        suffix = f", refresh #{snapshot.metadata_refresh[0]} {snapshot.metadata_refresh[1]}" if snapshot.metadata_refresh else ""
        metadata_level = "OK" if snapshot.metadata_rows else "WARN"
        if snapshot.metadata_refresh:
            refresh_status = snapshot.metadata_refresh[1]
            if refresh_status == "failed": metadata_level = "FAIL"
            elif refresh_status == "running" and metadata_level == "OK": metadata_level = "WARN"
        report.line(metadata_level, f"Metadata: {snapshot.metadata_rows} paths ({status}), latest #{snapshot.metadata_height or 'missing'}{suffix}")

    print("\nAPI")
    try:
        health = api_inspector()
        report.line("OK" if health.get("status") == "ok" else "FAIL", f"Health endpoint: status={health.get('status', 'missing')}, database={health.get('database', 'missing')}, indexed_height={health.get('indexed_height', 'missing')}, indexer_lag={health.get('indexer_lag', 'missing')}")
        if health.get("chain_id") != config.chain_id: report.line("FAIL", "API chain_id does not match configured chain")
        elif snapshot and health.get("indexed_height") != snapshot.indexed_height: report.line("WARN", "API and snapshot heights differ (indexing may have advanced)")
        else: report.line("OK", "API chain/indexer state consistent")
    except Exception as exc:
        report.line("FAIL", f"Health endpoint unreachable ({_safe_failure(exc)})")

    print(f"\nResult: {'HEALTHY' if report.failures == 0 else 'DEGRADED'}")
    print(f"Failures: {report.failures}\nWarnings: {report.warnings}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
