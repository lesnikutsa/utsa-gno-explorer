"""Bounded, transactional persistence for Realm and Package metadata snapshots.

The file fingerprint is SHA-256 over files sorted by UTF-8 filename.  Each filename
and content is encoded as an unsigned eight-byte big-endian length followed by its
exact UTF-8 bytes.  Length prefixes make the encoding unambiguous.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Literal

from .realm_metadata import (
    MAX_FILES, MAX_SOURCE_BYTES, MetadataParseError, _safe_filename, _validate_json,
    summarize_source_file,
)

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
CAPABILITY_STATUSES = frozenset({"ok", "not_applicable", "application_error", "rpc_error", "invalid_response"})
COLLECTION_STATUSES = frozenset({"complete", "partial"})
_CHAIN_RE = re.compile(r"^[!-~]{1,128}$")
_PATH_RE = re.compile(r"^gno\.land/([rp])/[!-\.0-~]+(?:/[!-\.0-~]+)*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MetadataPersistenceError(ValueError):
    """Raised when a snapshot cannot satisfy the persistence contract."""


@dataclass(frozen=True)
class MetadataFile:
    filename: str
    content: str


@dataclass(frozen=True)
class JsonCapability:
    status: str
    summary: Any | None = None
    payload: Any | None = None


@dataclass(frozen=True)
class RenderCapability:
    status: str
    sha256: str | None = None
    byte_count: int | None = None
    line_count: int | None = None
    non_empty: bool | None = None


@dataclass(frozen=True)
class StorageCapability:
    status: str
    storage_bytes: int | None = None
    deposit_ugnot: int | None = None


@dataclass(frozen=True)
class MetadataSnapshot:
    chain_id: str
    path: str
    path_kind: Literal["realm", "package"]
    observed_height: int
    collection_status: Literal["complete", "partial"]
    files: tuple[MetadataFile, ...]
    collected_at: datetime
    source_rpc_endpoint_id: int | None = None
    qdoc: JsonCapability = JsonCapability("not_applicable")
    qpkg_json: JsonCapability = JsonCapability("not_applicable")
    qfuncs: JsonCapability = JsonCapability("not_applicable")
    qrender: RenderCapability = RenderCapability("not_applicable")
    qstorage: StorageCapability = StorageCapability("not_applicable")


@dataclass(frozen=True)
class PreparedFile:
    filename: str
    content: str
    file_kind: str
    byte_count: int
    line_count: int
    sha256: str
    package_declared: bool
    import_candidate_count: int
    imports: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PreparedSnapshot:
    snapshot: MetadataSnapshot
    files: tuple[PreparedFile, ...]
    content_sha256: str
    gno_file_count: int
    test_file_count: int
    has_gnomod: bool
    total_file_bytes: int
    total_file_lines: int
    dependency_count: int


@dataclass(frozen=True)
class MetadataRefreshState:
    chain_id: str
    observed_height: int
    run_status: Literal["running", "complete", "partial", "failed"]
    selected_path_count: int
    published_path_count: int
    failed_path_count: int
    started_at: datetime
    completed_at: datetime | None = None
    last_successful_height: int | None = None
    last_successful_at: datetime | None = None


def metadata_fingerprint(files: Iterable[MetadataFile]) -> str:
    """Return the ordering-independent fingerprint of exact names and contents."""
    encoded: list[tuple[bytes, bytes]] = []
    for item in files:
        if not isinstance(item.filename, str) or not isinstance(item.content, str):
            raise MetadataPersistenceError("invalid_file_type")
        try:
            encoded.append((item.filename.encode("utf-8", "strict"), item.content.encode("utf-8", "strict")))
        except UnicodeEncodeError as exc:
            raise MetadataPersistenceError("invalid_utf8") from exc
    digest = hashlib.sha256()
    for name, content in sorted(encoded):
        digest.update(len(name).to_bytes(8, "big")); digest.update(name)
        digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    return digest.hexdigest()


def _json(value: Any, *, top: tuple[type, ...]) -> Any:
    if not isinstance(value, top):
        raise MetadataPersistenceError("invalid_json_top_level")
    try:
        _validate_json(value)
        # A round trip excludes arbitrary objects, non-string keys and non-finite values.
        return json.loads(json.dumps(value, allow_nan=False, separators=(",", ":")))
    except (MetadataParseError, TypeError, ValueError, OverflowError) as exc:
        raise MetadataPersistenceError("invalid_json") from exc


def _capability(cap: JsonCapability) -> tuple[str, Any | None, Any | None]:
    if cap.status not in CAPABILITY_STATUSES:
        raise MetadataPersistenceError("invalid_capability_status")
    if cap.status == "ok":
        if cap.summary is None or cap.payload is None:
            raise MetadataPersistenceError("missing_success_payload")
        return cap.status, _json(cap.summary, top=(dict,)), _json(cap.payload, top=(dict, list))
    if cap.summary is not None or cap.payload is not None:
        raise MetadataPersistenceError("failed_capability_has_payload")
    return cap.status, None, None


def _canonical_import(value: str) -> tuple[str, str] | None:
    match = _PATH_RE.fullmatch(value)
    if not match or "?" in value or "#" in value:
        return None
    return value, "realm" if match.group(1) == "r" else "package"


def prepare_metadata_snapshot(snapshot: MetadataSnapshot) -> PreparedSnapshot:
    if not _CHAIN_RE.fullmatch(snapshot.chain_id):
        raise MetadataPersistenceError("invalid_chain_id")
    match = _PATH_RE.fullmatch(snapshot.path)
    expected_kind = "realm" if match and match.group(1) == "r" else "package" if match else None
    if expected_kind is None or snapshot.path_kind != expected_kind or "?" in snapshot.path or "#" in snapshot.path:
        raise MetadataPersistenceError("invalid_path")
    if snapshot.observed_height <= 0 or snapshot.collection_status not in COLLECTION_STATUSES:
        raise MetadataPersistenceError("invalid_snapshot_state")
    if not isinstance(snapshot.collected_at, datetime):
        raise MetadataPersistenceError("invalid_collected_at")
    if len(snapshot.files) > MAX_FILES:
        raise MetadataPersistenceError("too_many_files")
    if len({item.filename for item in snapshot.files}) != len(snapshot.files):
        raise MetadataPersistenceError("duplicate_filename")
    qdoc = _capability(snapshot.qdoc); qpkg = _capability(snapshot.qpkg_json); qfuncs = _capability(snapshot.qfuncs)
    del qdoc, qpkg, qfuncs
    if snapshot.qrender.status not in CAPABILITY_STATUSES or snapshot.qstorage.status not in CAPABILITY_STATUSES:
        raise MetadataPersistenceError("invalid_capability_status")
    if snapshot.path_kind == "package" and (snapshot.qrender.status != "not_applicable" or snapshot.qstorage.status != "not_applicable"):
        raise MetadataPersistenceError("package_realm_capability")
    render = snapshot.qrender
    if render.status == "ok":
        if not (_SHA_RE.fullmatch(render.sha256 or "") and isinstance(render.byte_count, int) and render.byte_count >= 0 and isinstance(render.line_count, int) and render.line_count >= 0 and isinstance(render.non_empty, bool)):
            raise MetadataPersistenceError("invalid_qrender")
    elif any(value is not None for value in (render.sha256, render.byte_count, render.line_count, render.non_empty)):
        raise MetadataPersistenceError("failed_qrender_has_summary")
    storage = snapshot.qstorage
    if storage.status == "ok":
        if not (isinstance(storage.storage_bytes, int) and 0 <= storage.storage_bytes < 10**40 and isinstance(storage.deposit_ugnot, int) and 0 <= storage.deposit_ugnot < 10**40):
            raise MetadataPersistenceError("invalid_qstorage")
    elif storage.storage_bytes is not None or storage.deposit_ugnot is not None:
        raise MetadataPersistenceError("failed_qstorage_has_summary")

    prepared: list[PreparedFile] = []
    total = 0
    for item in snapshot.files:
        if not _safe_filename(item.filename):
            raise MetadataPersistenceError("invalid_filename")
        if not isinstance(item.content, str):
            raise MetadataPersistenceError("invalid_file_type")
        try:
            raw = item.content.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise MetadataPersistenceError("invalid_utf8") from exc
        if len(raw) > MAX_SOURCE_BYTES:
            raise MetadataPersistenceError("file_too_large")
        total += len(raw)
        if total > MAX_SNAPSHOT_BYTES:
            raise MetadataPersistenceError("snapshot_too_large")
        imports: tuple[tuple[str, str], ...] = ()
        package_declared = False; candidate_count = 0
        if item.filename.endswith(".gno"):
            try:
                summary = summarize_source_file(item.filename, item.content)
            except MetadataParseError as exc:
                raise MetadataPersistenceError("invalid_source") from exc
            package_declared = summary["package_declared"]; candidate_count = summary["import_candidate_count"]
            imports = tuple(sorted(filter(None, (_canonical_import(value) for value in summary["gno_land_imports"]))))
        kind = "gno_test" if item.filename.endswith("_test.gno") else "gno_source" if item.filename.endswith(".gno") else "gnomod" if item.filename == "gnomod.toml" else "other"
        prepared.append(PreparedFile(item.filename, item.content, kind, len(raw), len(item.content.splitlines()), hashlib.sha256(raw).hexdigest(), package_declared, candidate_count, imports))
    distinct = {path for item in prepared for path, _ in item.imports}
    return PreparedSnapshot(snapshot, tuple(prepared), metadata_fingerprint(snapshot.files), sum(f.file_kind in {"gno_source","gno_test"} for f in prepared), sum(f.file_kind == "gno_test" for f in prepared), any(f.file_kind == "gnomod" for f in prepared), total, sum(f.line_count for f in prepared), len(distinct))


def _preserved(current: dict[str, Any], name: str, status: str, values: tuple[Any, ...], height: int) -> tuple[Any, ...]:
    if status == "ok":
        return (*values, height)
    return tuple(current.get(f"{name}_{field}") for field in ("summary", "payload", "last_successful_height"))


def publish_metadata_snapshot_cursor(cursor, snapshot: MetadataSnapshot, *, before_children: Callable[[], None] | None = None) -> PreparedSnapshot:
    """Publish one validated snapshot using the caller's transaction."""
    prepared = prepare_metadata_snapshot(snapshot)
    cursor.execute("SELECT * FROM realm_metadata WHERE chain_id=%s AND path=%s FOR UPDATE", (snapshot.chain_id, snapshot.path))
    row = cursor.fetchone(); columns = [item[0] for item in cursor.description] if row else []
    current = dict(zip(columns, row)) if row else {}
    qdoc = _capability(snapshot.qdoc); qpkg = _capability(snapshot.qpkg_json); qfuncs = _capability(snapshot.qfuncs)
    def json_values(name: str, cap: tuple[str, Any | None, Any | None]) -> tuple[Any, Any, Any]:
        return (cap[1], cap[2], snapshot.observed_height) if cap[0] == "ok" else (current.get(name+"_summary"), current.get(name+"_payload"), current.get(name+"_last_successful_height"))
    qdv=json_values("qdoc",qdoc); qpv=json_values("qpkg_json",qpkg); qfv=json_values("qfuncs",qfuncs)
    rv=(snapshot.qrender.sha256,snapshot.qrender.byte_count,snapshot.qrender.line_count,snapshot.qrender.non_empty,snapshot.observed_height) if snapshot.qrender.status=="ok" else tuple(current.get("qrender_"+x) for x in ("sha256","byte_count","line_count","non_empty","last_successful_height"))
    sv=(snapshot.qstorage.storage_bytes,snapshot.qstorage.deposit_ugnot,snapshot.observed_height) if snapshot.qstorage.status=="ok" else tuple(current.get("qstorage_"+x) for x in ("bytes","deposit_ugnot","last_successful_height"))
    def db_json(value: Any | None) -> str | None:
        return None if value is None else json.dumps(value, allow_nan=False, separators=(",", ":"))
    qdv=(db_json(qdv[0]),db_json(qdv[1]),qdv[2]); qpv=(db_json(qpv[0]),db_json(qpv[1]),qpv[2]); qfv=(db_json(qfv[0]),db_json(qfv[1]),qfv[2])
    values=(snapshot.chain_id,snapshot.path,snapshot.path_kind,snapshot.observed_height,snapshot.collection_status,prepared.content_sha256,len(prepared.files),prepared.gno_file_count,prepared.test_file_count,prepared.has_gnomod,prepared.total_file_bytes,prepared.total_file_lines,prepared.dependency_count,snapshot.source_rpc_endpoint_id,qdoc[0],*qdv,qpkg[0],*qpv,qfuncs[0],*qfv,snapshot.qrender.status,*rv,snapshot.qstorage.status,*sv,snapshot.collected_at)
    names="chain_id,path,path_kind,observed_height,collection_status,content_sha256,file_count,gno_file_count,test_file_count,has_gnomod,total_file_bytes,total_file_lines,dependency_count,source_rpc_endpoint_id,qdoc_status,qdoc_summary,qdoc_payload,qdoc_last_successful_height,qpkg_json_status,qpkg_json_summary,qpkg_json_payload,qpkg_json_last_successful_height,qfuncs_status,qfuncs_summary,qfuncs_payload,qfuncs_last_successful_height,qrender_status,qrender_sha256,qrender_byte_count,qrender_line_count,qrender_non_empty,qrender_last_successful_height,qstorage_status,qstorage_bytes,qstorage_deposit_ugnot,qstorage_last_successful_height,collected_at"
    cursor.execute(f"INSERT INTO realm_metadata ({names}) VALUES ({','.join(['%s']*len(values))}) ON CONFLICT(chain_id,path) DO UPDATE SET "+",".join(f"{name}=EXCLUDED.{name}" for name in names.split(",") if name not in {"chain_id","path"})+",updated_at=now()", values)
    changed = not current or current.get("content_sha256") != prepared.content_sha256
    if changed:
        if before_children: before_children()
        cursor.execute("DELETE FROM realm_metadata_files WHERE chain_id=%s AND path=%s",(snapshot.chain_id,snapshot.path))
        for item in prepared.files:
            cursor.execute("INSERT INTO realm_metadata_files(chain_id,path,filename,file_kind,content,byte_count,line_count,sha256,package_declared,import_candidate_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(snapshot.chain_id,snapshot.path,item.filename,item.file_kind,item.content,item.byte_count,item.line_count,item.sha256,item.package_declared,item.import_candidate_count))
            for imported_path, imported_kind in item.imports:
                cursor.execute("INSERT INTO realm_metadata_imports(chain_id,path,source_filename,imported_path,imported_kind) VALUES (%s,%s,%s,%s,%s)",(snapshot.chain_id,snapshot.path,item.filename,imported_path,imported_kind))
    return prepared


def publish_metadata_snapshot(connection, snapshot: MetadataSnapshot, *, before_children: Callable[[], None] | None = None) -> PreparedSnapshot:
    """Publish atomically; the connection context rolls back every change on failure."""
    with connection:
        with connection.cursor() as cursor:
            return publish_metadata_snapshot_cursor(cursor, snapshot, before_children=before_children)


def persist_metadata_refresh_state_cursor(cursor, state: MetadataRefreshState) -> None:
    """Validate and upsert collector run state without performing collector work."""
    if not _CHAIN_RE.fullmatch(state.chain_id) or state.observed_height <= 0:
        raise MetadataPersistenceError("invalid_refresh_state")
    if state.run_status not in {"running", "complete", "partial", "failed"}:
        raise MetadataPersistenceError("invalid_refresh_state")
    counts=(state.selected_path_count,state.published_path_count,state.failed_path_count)
    if any(not isinstance(value,int) or value < 0 for value in counts) or sum(counts[1:]) > counts[0]:
        raise MetadataPersistenceError("invalid_refresh_state")
    if not isinstance(state.started_at,datetime) or ((state.run_status == "running") != (state.completed_at is None)):
        raise MetadataPersistenceError("invalid_refresh_state")
    if (state.last_successful_height is None) != (state.last_successful_at is None) or (state.last_successful_height is not None and state.last_successful_height <= 0):
        raise MetadataPersistenceError("invalid_refresh_state")
    cursor.execute("""INSERT INTO realm_metadata_refresh_state(chain_id,observed_height,run_status,selected_path_count,published_path_count,failed_path_count,started_at,completed_at,last_successful_height,last_successful_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id) DO UPDATE SET observed_height=EXCLUDED.observed_height,run_status=EXCLUDED.run_status,selected_path_count=EXCLUDED.selected_path_count,published_path_count=EXCLUDED.published_path_count,failed_path_count=EXCLUDED.failed_path_count,started_at=EXCLUDED.started_at,completed_at=EXCLUDED.completed_at,last_successful_height=EXCLUDED.last_successful_height,last_successful_at=EXCLUDED.last_successful_at,updated_at=now()""",(state.chain_id,state.observed_height,state.run_status,*counts,state.started_at,state.completed_at,state.last_successful_height,state.last_successful_at))
