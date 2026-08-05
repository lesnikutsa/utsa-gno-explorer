"""Bounded parsers for one-shot Realm and Package RPC metadata probes."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from scripts.inspect_rpc import MAX_ABCI_RESPONSE_BYTES

MAX_FILES = 256
MAX_FILENAME_LENGTH = 160
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCE_LINES = 100_000
MAX_IMPORT_CANDIDATES = 1_000
MAX_FUNCS = 1_000
MAX_FUNC_NAME_LENGTH = 160
MAX_QDOC_ITEMS = 1_000
MAX_JSON_DEPTH = 24
MAX_JSON_NODES = 20_000
MAX_STRING_LENGTH = 16_384
MAX_STORAGE_DIGITS = 40

class MetadataParseError(ValueError):
    """Raised when an RPC metadata payload is malformed or unsafe."""


def _text(payload: bytes | str, *, max_bytes: int = MAX_ABCI_RESPONSE_BYTES) -> str:
    if isinstance(payload, bytes):
        if len(payload) > max_bytes:
            raise MetadataParseError("oversized")
        try:
            return payload.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise MetadataParseError("invalid_utf8") from exc
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > max_bytes:
            raise MetadataParseError("oversized")
        return payload
    raise MetadataParseError("invalid_payload_type")


def _safe_filename(name: str) -> bool:
    return (
        isinstance(name, str)
        and 1 <= len(name) <= MAX_FILENAME_LENGTH
        and not name.startswith("/")
        and ".." not in name.split("/")
        and "\\" not in name
        and all(ord(ch) >= 32 and ord(ch) != 127 for ch in name)
        and all(part for part in name.split("/"))
    )


def parse_qfile_listing(payload: bytes | str) -> dict[str, Any]:
    text = _text(payload)
    lines = text.splitlines()
    if len(lines) > MAX_FILES:
        raise MetadataParseError("too_many_files")
    seen: set[str] = set()
    filenames: list[str] = []
    for line in lines:
        if not _safe_filename(line):
            raise MetadataParseError("invalid_filename")
        if line in seen:
            raise MetadataParseError("duplicate_filename")
        seen.add(line)
        filenames.append(line)
    gno_files = [name for name in filenames if name.endswith(".gno")]
    return {
        "file_count": len(filenames),
        "gno_file_count": len(gno_files),
        "test_file_count": sum(1 for name in gno_files if name.endswith("_test.gno")),
        "has_gnomod": "gnomod.toml" in filenames,
        "filenames": filenames,
    }

_IMPORT_RE = re.compile(r'(?m)^\s*import\s+(?:\(.*?\)|(?P<one>"[^"]+"))', re.S)
_QUOTED_RE = re.compile(r'"([^"]+)"')
_PACKAGE_RE = re.compile(r'(?m)^\s*package\s+[A-Za-z_][A-Za-z0-9_]*\s*$')


def summarize_source_file(filename: str, payload: bytes | str) -> dict[str, Any]:
    if not _safe_filename(filename) or not filename.endswith(".gno"):
        raise MetadataParseError("invalid_filename")
    text = _text(payload, max_bytes=MAX_SOURCE_BYTES)
    byte_count = len(text.encode("utf-8"))
    line_count = len(text.splitlines())
    if line_count > MAX_SOURCE_LINES:
        raise MetadataParseError("too_many_lines")
    candidates: list[str] = []
    for match in _IMPORT_RE.finditer(text):
        block = match.group(0)
        for value in _QUOTED_RE.findall(block):
            candidates.append(value)
            if len(candidates) > MAX_IMPORT_CANDIDATES:
                raise MetadataParseError("too_many_imports")
    gno_imports = sorted({value for value in candidates if value.startswith("gno.land/")})
    return {
        "filename": filename,
        "byte_count": byte_count,
        "line_count": line_count,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "package_declared": bool(_PACKAGE_RE.search(text)),
        "import_candidate_count": len(candidates),
        "gno_land_import_count": len(gno_imports),
        "gno_land_imports": gno_imports,
    }


def _load_json(payload: bytes | str) -> Any:
    text = _text(payload)
    def reject_constant(value: str) -> None:
        raise MetadataParseError("invalid_json_constant")
    try:
        return json.loads(text, parse_constant=reject_constant), len(text.encode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MetadataParseError("malformed_json") from exc


def _validate_json(value: Any, depth: int = 0, state: dict[str, int] | None = None) -> tuple[int, int]:
    if state is None:
        state = {"nodes": 0, "max_depth": 0}
    if depth > MAX_JSON_DEPTH:
        raise MetadataParseError("excessive_depth")
    state["nodes"] += 1
    state["max_depth"] = max(state["max_depth"], depth)
    if state["nodes"] > MAX_JSON_NODES:
        raise MetadataParseError("excessive_nodes")
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        raise MetadataParseError("string_too_long")
    if isinstance(value, float) and not math.isfinite(value):
        raise MetadataParseError("non_finite_number")
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth + 1, state)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > MAX_STRING_LENGTH:
                raise MetadataParseError("invalid_key")
            _validate_json(item, depth + 1, state)
    return state["max_depth"], state["nodes"]


def parse_qfuncs(payload: bytes | str) -> dict[str, Any]:
    data, _ = _load_json(payload)
    if not isinstance(data, list):
        raise MetadataParseError("wrong_top_level")
    if len(data) > MAX_FUNCS:
        raise MetadataParseError("too_many_functions")
    names: list[str] = []
    with_params = with_results = 0
    seen: set[str] = set(); duplicate = False
    for func in data:
        if not isinstance(func, dict):
            raise MetadataParseError("invalid_function")
        _validate_json(func)
        name = func.get("FuncName")
        if not isinstance(name, str) or not 1 <= len(name) <= MAX_FUNC_NAME_LENGTH or not name.isprintable():
            raise MetadataParseError("invalid_function_name")
        for field in ("Params", "Results"):
            if func.get(field) is not None and not isinstance(func.get(field), list):
                raise MetadataParseError("invalid_signature")
            for item in func.get(field) or []:
                if not isinstance(item, dict):
                    raise MetadataParseError("invalid_signature_item")
        duplicate = duplicate or name in seen; seen.add(name); names.append(name)
        with_params += bool(func.get("Params")); with_results += bool(func.get("Results"))
    return {"function_count": len(data), "function_names": names[:50], "functions_with_params": with_params, "functions_with_results": with_results, "duplicate_names": duplicate}


def parse_qdoc(payload: bytes | str, requested_path: str | None = None) -> dict[str, Any]:
    data, byte_count = _load_json(payload)
    if not isinstance(data, dict):
        raise MetadataParseError("wrong_top_level")
    _validate_json(data)
    package_path = data.get("package_path") or data.get("PackagePath") or data.get("Path")
    if requested_path is not None and package_path is not None and package_path != requested_path:
        raise MetadataParseError("path_mismatch")
    funcs = data.get("Funcs") or data.get("funcs") or []
    values = data.get("Values") or data.get("values") or []
    types = data.get("Types") or data.get("types") or []
    for collection in (funcs, values, types):
        if not isinstance(collection, list) or len(collection) > MAX_QDOC_ITEMS:
            raise MetadataParseError("invalid_doc_collection")
    return {"available": True, "package_doc_present": bool(data.get("Doc") or data.get("doc")), "documented_function_count": len(funcs), "value_count": len(values), "type_count": len(types), "byte_count": byte_count}


def parse_qpkg_json(payload: bytes | str) -> dict[str, Any]:
    data, byte_count = _load_json(payload)
    if not isinstance(data, (dict, list)):
        raise MetadataParseError("wrong_top_level")
    max_depth, nodes = _validate_json(data)
    return {"available": True, "top_level_type": type(data).__name__, "top_level_keys": sorted(data.keys())[:50] if isinstance(data, dict) else [], "byte_count": byte_count, "maximum_depth": max_depth, "node_count": nodes}


def summarize_qrender(payload: bytes | str) -> dict[str, Any]:
    text = _text(payload)
    raw = text.encode("utf-8")
    return {"byte_count": len(raw), "line_count": len(text.splitlines()), "non_empty": bool(text.strip()), "sha256": hashlib.sha256(raw).hexdigest()}

_STORAGE_RE = re.compile(r"\Astorage: ([0-9]+), deposit: ([0-9]+)\Z")


def parse_qstorage(payload: bytes | str) -> dict[str, Any]:
    text = _text(payload)
    match = _STORAGE_RE.fullmatch(text)
    if not match:
        raise MetadataParseError("malformed_storage")
    storage, deposit = match.groups()
    if len(storage) > MAX_STORAGE_DIGITS or len(deposit) > MAX_STORAGE_DIGITS:
        raise MetadataParseError("integer_too_large")
    return {"storage_bytes": int(storage), "deposit_ugnot": int(deposit)}
