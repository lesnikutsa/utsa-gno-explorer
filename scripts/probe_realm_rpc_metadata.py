#!/usr/bin/env python3
"""One-shot capability probe for bounded Realm and Package RPC metadata queries.

Exit codes: 0 means probes completed with core qfile/qfuncs/qdoc results processed;
1 means configuration, CLI, or no meaningful path probe failure; 2 means a report was
produced but at least one response was malformed or oversized.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from indexer.config import load_config
from indexer.realm_catalog import path_kind
from indexer.realm_metadata import (
    MetadataParseError, parse_qdoc, parse_qfile_listing, parse_qfuncs,
    parse_qpkg_json, parse_qstorage, summarize_qrender, summarize_source_file,
)
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_probes
from scripts.inspect_rpc import GnoRpcClient, MAX_ABCI_RESPONSE_BYTES, RpcError

STATUSES = {"ok", "application_error", "rpc_error", "malformed", "oversized", "not_applicable", "skipped"}
SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REPORT_LIMIT_BYTES = 512 * 1024

@dataclass(frozen=True)
class QueryProbeResult:
    query_name: str
    status: str
    response_bytes: int
    elapsed_seconds: float
    summary: dict[str, Any]
    safe_error_code: str | None = None

@dataclass(frozen=True)
class PathProbeResult:
    path: str
    kind: str
    rpc_host: str
    height: int
    queries: list[QueryProbeResult]
    overall_status: str


def safe_host(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.hostname or "unknown-host"


def _safe_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "application error" in text:
        return "application_error"
    if "oversized" in text or "exceeds size" in text:
        return "oversized"
    code = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:64]
    return code if SAFE_ERROR_RE.fullmatch(code) else "probe_error"


def _query(client: GnoRpcClient, name: str, path: str, data: str, height: int, parser: Callable[[str], dict[str, Any]]) -> QueryProbeResult:
    started = time.perf_counter()
    try:
        payload = client.abci_query(path, data, height=height)
        response_bytes = len(payload.encode("utf-8"))
        summary = parser(payload)
        status = "ok"
        error = None
    except MetadataParseError as exc:
        response_bytes = 0
        status = "oversized" if str(exc) == "oversized" else "malformed"
        summary = {}
        error = _safe_error(exc)
    except RpcError as exc:
        response_bytes = 0
        code = _safe_error(exc)
        status = "application_error" if code == "application_error" else ("oversized" if code == "oversized" else "rpc_error")
        summary = {}
        error = code
    elapsed = time.perf_counter() - started
    return QueryProbeResult(name, status, response_bytes, round(elapsed, 6), summary, error)


def source_sample_name(listing: dict[str, Any]) -> str | None:
    filenames = listing.get("filenames") if isinstance(listing, dict) else []
    gno_files = [name for name in filenames if isinstance(name, str) and name.endswith(".gno")]
    return next((name for name in gno_files if not name.endswith("_test.gno")), None) or (gno_files[0] if gno_files else None)


def probe_path(client: GnoRpcClient, rpc_host: str, height: int, path: str, kind: str) -> PathProbeResult:
    queries: list[QueryProbeResult] = []
    listing_summary: dict[str, Any] | None = None
    qfile_listing = _query(client, "qfile_listing", "vm/qfile", path, height, parse_qfile_listing)
    queries.append(qfile_listing)
    if qfile_listing.status == "ok":
        listing_summary = qfile_listing.summary
        filename = source_sample_name(listing_summary)
        if filename:
            queries.append(_query(client, "qfile_source_sample", "vm/qfile", f"{path}/{filename}", height, lambda payload, filename=filename: summarize_source_file(filename, payload)))
        else:
            queries.append(QueryProbeResult("qfile_source_sample", "skipped", 0, 0.0, {"reason": "no_gno_file"}, None))
    else:
        queries.append(QueryProbeResult("qfile_source_sample", "skipped", 0, 0.0, {"reason": "listing_unavailable"}, None))
    queries.append(_query(client, "qfuncs", "vm/qfuncs", path, height, parse_qfuncs))
    queries.append(_query(client, "qdoc", "vm/qdoc", path, height, lambda payload: parse_qdoc(payload, requested_path=path)))
    queries.append(_query(client, "qpkg_json", "vm/qpkg_json", path, height, parse_qpkg_json))
    if kind == "realm":
        queries.append(_query(client, "qrender", "vm/qrender", f"{path}:", height, summarize_qrender))
        queries.append(_query(client, "qstorage", "vm/qstorage", path, height, parse_qstorage))
    else:
        queries.append(QueryProbeResult("qrender", "not_applicable", 0, 0.0, {}, None))
        queries.append(QueryProbeResult("qstorage", "not_applicable", 0, 0.0, {}, None))
    overall = "malformed" if any(q.status in {"malformed", "oversized"} for q in queries) else "ok"
    return PathProbeResult(path, kind, rpc_host, height, queries, overall)


def compact_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    allowed = {k: v for k, v in summary.items() if k not in {"filenames", "function_names", "gno_land_imports"}}
    return json.dumps(allowed, sort_keys=True, separators=(",", ":"))[:240]


def print_results(results: list[PathProbeResult]) -> None:
    for result in results:
        print(f"RPC host: {result.rpc_host}")
        print(f"height: {result.height}")
        print(f"path: {result.path} ({result.kind})")
        for query in result.queries:
            suffix = compact_summary(query.summary)
            error = f" error={query.safe_error_code}" if query.safe_error_code else ""
            print(f"- {query.query_name}: {query.status} {query.elapsed_seconds:.3f}s{error} {suffix}".rstrip())


def write_json_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise OSError("json output target must not be a symlink")
    if not path.parent.exists():
        raise OSError("json output parent directory does not exist")
    encoded = json.dumps(report, sort_keys=True, indent=2).encode("utf-8")
    if len(encoded) > REPORT_LIMIT_BYTES:
        raise OSError("json report exceeds size limit")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe bounded Realm and Package RPC metadata capabilities.")
    parser.add_argument("--realm-path", action="append", default=[])
    parser.add_argument("--package-path", action="append", default=[])
    parser.add_argument("--all-suitable-rpcs", action="store_true")
    parser.add_argument("--json-output")
    parser.add_argument("--timeout", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (1 <= args.timeout <= 60):
        parser.error("--timeout must be between 1 and 60 seconds")
    paths: list[tuple[str, str]] = []
    for value in args.realm_path:
        if path_kind(value) != "realm":
            parser.error("--realm-path must be a bounded gno.land/r/... Realm path")
        paths.append((value, "realm"))
    for value in args.package_path:
        if path_kind(value) != "package":
            parser.error("--package-path must be a bounded gno.land/p/... Package path")
        paths.append((value, "package"))
    if not paths:
        parser.error("at least one --realm-path or --package-path is required")
    try:
        config = load_config()
        probes = probe_rpc_endpoints(config.rpc_urls, config.chain_id, config.max_height_lag, timeout=args.timeout)
        suitable = suitable_rpc_probes(probes)
        if not suitable:
            print("No suitable RPC endpoints available", file=sys.stderr)
            return 1
        selected = suitable if args.all_suitable_rpcs else suitable[:1]
        results: list[PathProbeResult] = []
        try:
            for probe in selected:
                assert probe.client is not None and probe.latest_height is not None
                height = probe.latest_height - 1
                if height < 1:
                    continue
                for probe_path_value, kind in paths:
                    results.append(probe_path(probe.client, safe_host(probe.url), height, probe_path_value, kind))
        finally:
            for probe in probes:
                close = getattr(probe.client, "close", None)
                if callable(close):
                    close()
        if not results:
            return 1
        print_results(results)
        report = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "chain_id": config.chain_id, "endpoints": [asdict(result) for result in results]}
        if args.json_output:
            write_json_report(Path(args.json_output), report)
        core_names = {"qfile_listing", "qfuncs", "qdoc"}
        meaningful = any(any(q.query_name in core_names and q.status in STATUSES - {"skipped", "not_applicable"} for q in result.queries) for result in results)
        if not meaningful:
            return 1
        if any(q.status in {"malformed", "oversized"} for result in results for q in result.queries):
            return 2
        return 0
    except (RpcError, OSError, ValueError) as exc:
        print(f"Probe failed: {_safe_error(exc)}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
