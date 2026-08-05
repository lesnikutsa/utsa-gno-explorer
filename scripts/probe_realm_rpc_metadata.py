#!/usr/bin/env python3
"""One-shot capability probe for bounded Realm and Package RPC metadata queries.

Exit codes: 0 means probes completed with a core qfile/qfuncs/qdoc status=ok;
1 means configuration, CLI, or no meaningful path probe failure; 2 means a report was
produced but at least one response was malformed or oversized.
"""
from __future__ import annotations

import argparse
import json
import math
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
from scripts.inspect_rpc import GnoRpcClient, RpcError

STATUSES = {"ok", "application_error", "rpc_error", "malformed", "oversized", "not_applicable", "skipped"}
OVERALL_STATUSES = {"ok", "partial", "unavailable", "malformed"}
SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_QUERY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REPORT_LIMIT_BYTES = 512 * 1024
MAX_PROBE_PATHS = 20
MAX_QUERIES_PER_PATH = 16
CORE_QUERY_NAMES = {"qfile_listing", "qfuncs", "qdoc"}
PARSER_ERROR_CODES = {
    "oversized", "invalid_utf8", "malformed_json", "wrong_top_level",
    "excessive_depth", "excessive_nodes", "invalid_filename",
    "duplicate_filename", "path_mismatch", "malformed_storage",
    "empty_listing", "too_many_files", "too_many_lines", "too_many_imports",
    "invalid_payload_type", "invalid_json_constant", "string_too_long",
    "non_finite_number", "invalid_key", "too_many_functions",
    "invalid_function", "invalid_function_name", "invalid_signature",
    "invalid_signature_item", "invalid_doc_collection", "invalid_package_doc",
    "integer_too_large",
}

@dataclass(frozen=True)
class QueryProbeResult:
    query_name: str
    status: str
    response_bytes: int
    elapsed_seconds: float
    summary: dict[str, Any]
    safe_error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query_name, str) or not SAFE_QUERY_RE.fullmatch(self.query_name):
            raise ValueError("query_name must be a bounded safe identifier")
        if self.status not in STATUSES:
            raise ValueError("invalid query status")
        if not isinstance(self.response_bytes, int) or isinstance(self.response_bytes, bool) or self.response_bytes < 0:
            raise ValueError("response_bytes must be a non-negative integer")
        if not isinstance(self.elapsed_seconds, (int, float)) or isinstance(self.elapsed_seconds, bool) or not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be finite and non-negative")
        if not isinstance(self.summary, dict):
            raise ValueError("summary must be a dict")
        if self.safe_error_code is not None and not SAFE_ERROR_RE.fullmatch(self.safe_error_code):
            raise ValueError("safe_error_code must be sanitized")
        if self.status == "ok" and self.safe_error_code is not None:
            raise ValueError("ok status cannot include safe_error_code")
        if self.status in {"application_error", "rpc_error", "malformed", "oversized"} and self.safe_error_code is None:
            raise ValueError("error status requires safe_error_code")


@dataclass(frozen=True)
class PathProbeResult:
    path: str
    kind: str
    rpc_host: str
    height: int
    queries: list[QueryProbeResult]
    overall_status: str

    def __post_init__(self) -> None:
        if path_kind(self.path) != self.kind:
            raise ValueError("path kind mismatch")
        if not isinstance(self.rpc_host, str) or not 1 <= len(self.rpc_host) <= 253 or any(token in self.rpc_host for token in ("@", ":", "/", "?", "#")):
            raise ValueError("rpc_host must be sanitized")
        if not isinstance(self.height, int) or isinstance(self.height, bool) or self.height < 1:
            raise ValueError("height must be a positive integer")
        if not isinstance(self.queries, list) or not 1 <= len(self.queries) <= MAX_QUERIES_PER_PATH:
            raise ValueError("queries must be a bounded non-empty list")
        names = [query.query_name for query in self.queries]
        if len(names) != len(set(names)):
            raise ValueError("duplicate query_name")
        if self.overall_status not in OVERALL_STATUSES:
            raise ValueError("invalid overall_status")


def safe_host(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.hostname or "unknown-host"


def _validated_error_code(code: str) -> str:
    if not SAFE_ERROR_RE.fullmatch(code):
        raise ValueError("unsafe internal error code")
    return code


def parser_error_code(exc: MetadataParseError) -> str:
    code = exc.args[0] if exc.args and isinstance(exc.args[0], str) else ""
    return _validated_error_code(code if code in PARSER_ERROR_CODES else "metadata_parse_error")


def rpc_error_code(exc: RpcError) -> str:
    message = str(exc)
    if message.startswith("RPC request timed out for "):
        return _validated_error_code("rpc_timeout")
    if message.startswith("RPC request failed for "):
        return _validated_error_code("rpc_request_failed")
    if message.startswith("RPC response for ") and message.endswith(" was not valid JSON"):
        return _validated_error_code("rpc_invalid_json")
    if message.startswith("RPC returned an error for "):
        return _validated_error_code("rpc_payload_error")
    exact = {
        "ABCI query returned an application error": "application_error",
        "Malformed ABCI response": "malformed_abci_response",
        "Malformed or oversized ABCI response data": "malformed_abci_data",
        "Malformed ABCI response data": "malformed_abci_data",
        "ABCI response exceeds size limit": "oversized",
        "ABCI response data is not UTF-8": "invalid_utf8",
    }
    return _validated_error_code(exact.get(message, "rpc_error"))


def _query(client: GnoRpcClient, name: str, path: str, data: str, height: int, parser: Callable[[str], dict[str, Any]]) -> QueryProbeResult:
    started = time.perf_counter()
    response_bytes = 0
    try:
        payload = client.abci_query(path, data, height=height)
        response_bytes = len(payload.encode("utf-8"))
        summary = parser(payload)
        status = "ok"
        error = None
    except MetadataParseError as exc:
        code = parser_error_code(exc)
        status = "oversized" if code == "oversized" else "malformed"
        summary = {}
        error = code
    except RpcError as exc:
        code = rpc_error_code(exc)
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
    return PathProbeResult(path, kind, rpc_host, height, queries, overall_status(queries))


def overall_status(queries: list[QueryProbeResult]) -> str:
    if any(query.status in {"malformed", "oversized"} for query in queries):
        return "malformed"
    has_core_ok = any(query.query_name in CORE_QUERY_NAMES and query.status == "ok" for query in queries)
    if not has_core_ok:
        return "unavailable"
    if any(query.status in {"application_error", "rpc_error"} for query in queries):
        return "partial"
    return "ok"


def compact_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    allowed = {k: v for k, v in summary.items() if k not in {"filenames", "function_names", "gno_land_imports"}}
    return json.dumps(allowed, sort_keys=True, separators=(",", ":"))[:240]




def close_rpc_probes(probes: list[Any]) -> None:
    for probe in probes:
        close = getattr(getattr(probe, "client", None), "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

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


class ExitOneArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = ExitOneArgumentParser(description="Probe bounded Realm and Package RPC metadata capabilities.")
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
    seen_paths: set[str] = set()
    for value in args.realm_path:
        if path_kind(value) != "realm":
            parser.error("--realm-path must be a bounded gno.land/r/... Realm path")
        if value in seen_paths:
            parser.error("duplicate Realm or Package path")
        seen_paths.add(value)
        paths.append((value, "realm"))
    for value in args.package_path:
        if path_kind(value) != "package":
            parser.error("--package-path must be a bounded gno.land/p/... Package path")
        if value in seen_paths:
            parser.error("duplicate Realm or Package path")
        seen_paths.add(value)
        paths.append((value, "package"))
    if not paths:
        parser.error("at least one --realm-path or --package-path is required")
    if len(paths) > MAX_PROBE_PATHS:
        parser.error(f"at most {MAX_PROBE_PATHS} total Realm and Package paths are allowed")
    probes = []
    try:
        config = load_config()
        probes = probe_rpc_endpoints(config.rpc_urls, config.chain_id, config.max_height_lag, timeout=args.timeout)
        try:
            suitable = suitable_rpc_probes(probes)
            if not suitable:
                print("No suitable RPC endpoints available", file=sys.stderr)
                return 1
            selected = suitable if args.all_suitable_rpcs else suitable[:1]
            results: list[PathProbeResult] = []
            for probe in selected:
                assert probe.client is not None and probe.latest_height is not None
                height = probe.latest_height - 1
                if height < 1:
                    continue
                for probe_path_value, kind in paths:
                    results.append(probe_path(probe.client, safe_host(probe.url), height, probe_path_value, kind))
            if not results:
                return 1
            print_results(results)
            report = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "chain_id": config.chain_id, "endpoints": [asdict(result) for result in results]}
            if args.json_output:
                write_json_report(Path(args.json_output), report)
            if any(q.status in {"malformed", "oversized"} for result in results for q in result.queries):
                return 2
            meaningful = any(
                q.query_name in CORE_QUERY_NAMES and q.status == "ok"
                for result in results
                for q in result.queries
            )
            if not meaningful:
                return 1
            return 0
        finally:
            close_rpc_probes(probes)
    except RpcError as exc:
        print(f"Probe failed: {rpc_error_code(exc)}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Probe failed: probe_error", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
