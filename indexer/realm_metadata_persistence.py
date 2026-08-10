"""Bounded, transactional persistence for Realm and Package metadata snapshots.

The file fingerprint is SHA-256 over files sorted by UTF-8 filename. Each filename
and content is encoded as an unsigned eight-byte big-endian length followed by its
exact UTF-8 bytes. Length prefixes make the encoding unambiguous.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal

from scripts.inspect_rpc import MAX_ABCI_RESPONSE_BYTES

from .realm_metadata import (
    MAX_FILES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_LINES,
    MetadataParseError,
    _load_json,
    _safe_filename,
    parse_qdoc,
    parse_qfile_listing,
    parse_qfuncs,
    parse_qpkg_json,
    summarize_source_file,
)

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
CAPABILITY_STATUSES = frozenset(
    {"ok", "not_applicable", "application_error", "rpc_error", "invalid_response"}
)
COLLECTION_STATUSES = frozenset({"complete", "partial"})
_CHAIN_RE = re.compile(r"^[!-~]{1,128}$")
_PATH_RE = re.compile(r"^gno\.land/([rp])/[!-\.0-~]+(?:/[!-\.0-~]+)*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MetadataPersistenceError(ValueError):
    """Raised with a stable bounded code when persistence input is unsafe."""


class StaleMetadataSnapshot(MetadataPersistenceError):
    """Raised when a publication would regress the canonical snapshot."""


@dataclass(frozen=True)
class MetadataFile:
    filename: str
    content: str


@dataclass(frozen=True)
class JsonCapability:
    status: str
    payload: bytes | str | None = None


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
    expected_filenames: tuple[str, ...]
    files: tuple[MetadataFile, ...]
    collected_at: datetime
    source_rpc_endpoint_id: int | None = None
    qdoc: JsonCapability = JsonCapability("not_applicable")
    qpkg_json: JsonCapability = JsonCapability("not_applicable")
    qfuncs: JsonCapability = JsonCapability("not_applicable")
    qrender: RenderCapability = RenderCapability("not_applicable")
    qstorage: StorageCapability = StorageCapability("not_applicable")


@dataclass(frozen=True)
class PreparedJsonCapability:
    status: str
    summary: dict[str, Any] | None
    payload: dict[str, Any] | list[Any] | None


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
    qdoc: PreparedJsonCapability
    qpkg_json: PreparedJsonCapability
    qfuncs: PreparedJsonCapability


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


def _strict_int(value: object, *, minimum: int = 0, maximum: int | None = None) -> bool:
    return (
        type(value) is int
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def metadata_fingerprint(files: Iterable[MetadataFile]) -> str:
    """Return the ordering-independent fingerprint of exact names and contents."""
    encoded: list[tuple[bytes, bytes]] = []
    for item in files:
        if not isinstance(item.filename, str) or not isinstance(item.content, str):
            raise MetadataPersistenceError("invalid_file_type")
        try:
            encoded.append(
                (
                    item.filename.encode("utf-8", "strict"),
                    item.content.encode("utf-8", "strict"),
                )
            )
        except UnicodeEncodeError as exc:
            raise MetadataPersistenceError("invalid_utf8") from exc
    digest = hashlib.sha256()
    for name, content in sorted(encoded):
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _prepare_json_capability(
    name: str,
    capability: JsonCapability,
    *,
    requested_path: str,
) -> PreparedJsonCapability:
    if capability.status not in CAPABILITY_STATUSES:
        raise MetadataPersistenceError("invalid_capability_status")
    if capability.status != "ok":
        if capability.payload is not None:
            raise MetadataPersistenceError("failed_capability_has_payload")
        return PreparedJsonCapability(capability.status, None, None)
    if not isinstance(capability.payload, (bytes, str)):
        raise MetadataPersistenceError("missing_success_payload")
    try:
        if name == "qdoc":
            summary = parse_qdoc(capability.payload, requested_path=requested_path)
        elif name == "qpkg_json":
            summary = parse_qpkg_json(capability.payload)
        elif name == "qfuncs":
            summary = parse_qfuncs(capability.payload)
        else:  # pragma: no cover - private programming invariant
            raise AssertionError(name)
        payload, _ = _load_json(capability.payload)
    except MetadataParseError as exc:
        raise MetadataPersistenceError(f"invalid_{name}") from exc
    return PreparedJsonCapability(capability.status, summary, payload)


def _canonical_import(value: str) -> tuple[str, str] | None:
    match = _PATH_RE.fullmatch(value)
    if not match or "?" in value or "#" in value:
        return None
    return value, "realm" if match.group(1) == "r" else "package"


def _validate_listing(snapshot: MetadataSnapshot) -> None:
    if not snapshot.expected_filenames:
        raise MetadataPersistenceError("empty_listing")
    if not all(isinstance(name, str) for name in snapshot.expected_filenames):
        raise MetadataPersistenceError("invalid_listing")
    try:
        listing = parse_qfile_listing("\n".join(snapshot.expected_filenames))
    except MetadataParseError as exc:
        raise MetadataPersistenceError("invalid_listing") from exc
    if tuple(listing["filenames"]) != snapshot.expected_filenames:
        raise MetadataPersistenceError("invalid_listing")
    fetched = [item.filename for item in snapshot.files]
    if len(fetched) != len(set(fetched)):
        raise MetadataPersistenceError("duplicate_filename")
    expected = set(snapshot.expected_filenames)
    actual = set(fetched)
    if expected != actual:
        raise MetadataPersistenceError(
            "missing_listed_file" if expected - actual else "extra_fetched_file"
        )


def _validate_render(render: RenderCapability) -> None:
    if render.status not in CAPABILITY_STATUSES:
        raise MetadataPersistenceError("invalid_capability_status")
    values = (render.sha256, render.byte_count, render.line_count, render.non_empty)
    if render.status != "ok":
        if any(value is not None for value in values):
            raise MetadataPersistenceError("failed_qrender_has_summary")
        return
    valid = (
        _SHA_RE.fullmatch(render.sha256 or "") is not None
        and _strict_int(render.byte_count, maximum=MAX_ABCI_RESPONSE_BYTES)
        and _strict_int(render.line_count, maximum=MAX_ABCI_RESPONSE_BYTES)
        and isinstance(render.non_empty, bool)
        and render.line_count <= render.byte_count + 1
        and (render.byte_count != 0 or (render.line_count == 0 and not render.non_empty))
        and (not render.non_empty or render.byte_count > 0)
    )
    if not valid:
        raise MetadataPersistenceError("invalid_qrender")


def _validate_storage(storage: StorageCapability) -> None:
    if storage.status not in CAPABILITY_STATUSES:
        raise MetadataPersistenceError("invalid_capability_status")
    if storage.status != "ok":
        if storage.storage_bytes is not None or storage.deposit_ugnot is not None:
            raise MetadataPersistenceError("failed_qstorage_has_summary")
        return
    if not (
        _strict_int(storage.storage_bytes, maximum=10**40 - 1)
        and _strict_int(storage.deposit_ugnot, maximum=10**40 - 1)
    ):
        raise MetadataPersistenceError("invalid_qstorage")


def prepare_metadata_snapshot(snapshot: MetadataSnapshot) -> PreparedSnapshot:
    if not isinstance(snapshot.chain_id, str) or not _CHAIN_RE.fullmatch(snapshot.chain_id):
        raise MetadataPersistenceError("invalid_chain_id")
    match = _PATH_RE.fullmatch(snapshot.path) if isinstance(snapshot.path, str) else None
    expected_kind = "realm" if match and match.group(1) == "r" else "package" if match else None
    if (
        expected_kind is None
        or snapshot.path_kind != expected_kind
        or "?" in snapshot.path
        or "#" in snapshot.path
    ):
        raise MetadataPersistenceError("invalid_path")
    if not _strict_int(snapshot.observed_height, minimum=1):
        raise MetadataPersistenceError("invalid_observed_height")
    if snapshot.collection_status not in COLLECTION_STATUSES:
        raise MetadataPersistenceError("invalid_collection_status")
    if not _aware(snapshot.collected_at):
        raise MetadataPersistenceError("invalid_collected_at")
    if snapshot.source_rpc_endpoint_id is not None and not _strict_int(
        snapshot.source_rpc_endpoint_id, minimum=1
    ):
        raise MetadataPersistenceError("invalid_source_rpc_endpoint_id")
    _validate_listing(snapshot)

    qdoc = _prepare_json_capability("qdoc", snapshot.qdoc, requested_path=snapshot.path)
    qpkg = _prepare_json_capability("qpkg_json", snapshot.qpkg_json, requested_path=snapshot.path)
    qfuncs = _prepare_json_capability("qfuncs", snapshot.qfuncs, requested_path=snapshot.path)
    _validate_render(snapshot.qrender)
    _validate_storage(snapshot.qstorage)
    if snapshot.path_kind == "package" and (
        snapshot.qrender.status != "not_applicable"
        or snapshot.qstorage.status != "not_applicable"
    ):
        raise MetadataPersistenceError("package_realm_capability")

    prepared: list[PreparedFile] = []
    total_bytes = 0
    for item in snapshot.files:
        if not _safe_filename(item.filename):
            raise MetadataPersistenceError("invalid_filename")
        if not isinstance(item.content, str):
            raise MetadataPersistenceError("invalid_file_type")
        try:
            raw = item.content.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise MetadataPersistenceError("invalid_utf8") from exc
        line_count = len(item.content.splitlines())
        if len(raw) > MAX_SOURCE_BYTES:
            raise MetadataPersistenceError("file_too_large")
        if line_count > MAX_SOURCE_LINES:
            raise MetadataPersistenceError("too_many_lines")
        total_bytes += len(raw)
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise MetadataPersistenceError("snapshot_too_large")
        imports: tuple[tuple[str, str], ...] = ()
        package_declared = False
        candidate_count = 0
        if item.filename.endswith(".gno"):
            try:
                summary = summarize_source_file(item.filename, item.content)
            except MetadataParseError as exc:
                raise MetadataPersistenceError("invalid_source") from exc
            package_declared = summary["package_declared"]
            candidate_count = summary["import_candidate_count"]
            imports = tuple(
                sorted(
                    value
                    for value in (
                        _canonical_import(path) for path in summary["gno_land_imports"]
                    )
                    if value is not None
                )
            )
        if item.filename.endswith("_test.gno"):
            kind = "gno_test"
        elif item.filename.endswith(".gno"):
            kind = "gno_source"
        elif item.filename == "gnomod.toml":
            kind = "gnomod"
        else:
            kind = "other"
        prepared.append(
            PreparedFile(
                item.filename,
                item.content,
                kind,
                len(raw),
                line_count,
                hashlib.sha256(raw).hexdigest(),
                package_declared,
                candidate_count,
                imports,
            )
        )
    dependencies = {path for item in prepared for path, _ in item.imports}
    return PreparedSnapshot(
        snapshot=snapshot,
        files=tuple(prepared),
        content_sha256=metadata_fingerprint(snapshot.files),
        gno_file_count=sum(item.file_kind in {"gno_source", "gno_test"} for item in prepared),
        test_file_count=sum(item.file_kind == "gno_test" for item in prepared),
        has_gnomod=any(item.file_kind == "gnomod" for item in prepared),
        total_file_bytes=total_bytes,
        total_file_lines=sum(item.line_count for item in prepared),
        dependency_count=len(dependencies),
        qdoc=qdoc,
        qpkg_json=qpkg,
        qfuncs=qfuncs,
    )


_CURRENT_COLUMNS = (
    "observed_height", "collected_at", "content_sha256",
    "qdoc_summary", "qdoc_payload", "qdoc_last_successful_height",
    "qpkg_json_summary", "qpkg_json_payload", "qpkg_json_last_successful_height",
    "qfuncs_summary", "qfuncs_payload", "qfuncs_last_successful_height",
    "qrender_sha256", "qrender_byte_count", "qrender_line_count",
    "qrender_non_empty", "qrender_last_successful_height",
    "qstorage_bytes", "qstorage_deposit_ugnot", "qstorage_last_successful_height",
)


def _json_success_values(
    prepared: PreparedJsonCapability,
    current: dict[str, Any],
    prefix: str,
    height: int,
) -> tuple[Any, Any, int | None]:
    if prepared.status == "ok":
        return prepared.summary, prepared.payload, height
    return (
        current.get(f"{prefix}_summary"),
        current.get(f"{prefix}_payload"),
        current.get(f"{prefix}_last_successful_height"),
    )


def _render_success_values(
    snapshot: MetadataSnapshot, current: dict[str, Any]
) -> tuple[Any, Any, Any, Any, Any]:
    if snapshot.qrender.status == "ok":
        return (
            snapshot.qrender.sha256, snapshot.qrender.byte_count,
            snapshot.qrender.line_count, snapshot.qrender.non_empty,
            snapshot.observed_height,
        )
    return tuple(
        current.get(f"qrender_{name}")
        for name in ("sha256", "byte_count", "line_count", "non_empty", "last_successful_height")
    )


def _storage_success_values(
    snapshot: MetadataSnapshot, current: dict[str, Any]
) -> tuple[Any, Any, Any]:
    if snapshot.qstorage.status == "ok":
        return (
            snapshot.qstorage.storage_bytes,
            snapshot.qstorage.deposit_ugnot,
            snapshot.observed_height,
        )
    return tuple(
        current.get(f"qstorage_{name}")
        for name in ("bytes", "deposit_ugnot", "last_successful_height")
    )


def _json_parameter(value: Any) -> str | None:
    return None if value is None else json.dumps(value, allow_nan=False, separators=(",", ":"))


def publish_metadata_snapshot_cursor(cursor, snapshot: MetadataSnapshot) -> PreparedSnapshot:
    """Publish one validated snapshot using the caller's transaction."""
    prepared = prepare_metadata_snapshot(snapshot)
    cursor.execute(
        f"SELECT {', '.join(_CURRENT_COLUMNS)} FROM realm_metadata "
        "WHERE chain_id = %s AND path = %s FOR UPDATE",
        (snapshot.chain_id, snapshot.path),
    )
    row = cursor.fetchone()
    current = dict(zip(_CURRENT_COLUMNS, row)) if row is not None else {}
    if current:
        current_height = current["observed_height"]
        current_time = current["collected_at"]
        if current_height > snapshot.observed_height or (
            current_height == snapshot.observed_height
            and current_time > snapshot.collected_at
        ):
            raise StaleMetadataSnapshot("stale_metadata_snapshot")

    qdoc = _json_success_values(prepared.qdoc, current, "qdoc", snapshot.observed_height)
    qpkg = _json_success_values(prepared.qpkg_json, current, "qpkg_json", snapshot.observed_height)
    qfuncs = _json_success_values(prepared.qfuncs, current, "qfuncs", snapshot.observed_height)
    render = _render_success_values(snapshot, current)
    storage = _storage_success_values(snapshot, current)
    values = (
        snapshot.chain_id, snapshot.path, snapshot.path_kind,
        snapshot.observed_height, snapshot.collection_status,
        prepared.content_sha256, len(prepared.files), prepared.gno_file_count,
        prepared.test_file_count, prepared.has_gnomod, prepared.total_file_bytes,
        prepared.total_file_lines, prepared.dependency_count,
        snapshot.source_rpc_endpoint_id,
        prepared.qdoc.status, _json_parameter(qdoc[0]), _json_parameter(qdoc[1]), qdoc[2],
        prepared.qpkg_json.status, _json_parameter(qpkg[0]), _json_parameter(qpkg[1]), qpkg[2],
        prepared.qfuncs.status, _json_parameter(qfuncs[0]), _json_parameter(qfuncs[1]), qfuncs[2],
        snapshot.qrender.status, *render,
        snapshot.qstorage.status, *storage,
        snapshot.collected_at,
    )
    cursor.execute(
        """INSERT INTO realm_metadata (
          chain_id, path, path_kind, observed_height, collection_status,
          content_sha256, file_count, gno_file_count, test_file_count, has_gnomod,
          total_file_bytes, total_file_lines, dependency_count, source_rpc_endpoint_id,
          qdoc_status, qdoc_summary, qdoc_payload, qdoc_last_successful_height,
          qpkg_json_status, qpkg_json_summary, qpkg_json_payload, qpkg_json_last_successful_height,
          qfuncs_status, qfuncs_summary, qfuncs_payload, qfuncs_last_successful_height,
          qrender_status, qrender_sha256, qrender_byte_count, qrender_line_count,
          qrender_non_empty, qrender_last_successful_height,
          qstorage_status, qstorage_bytes, qstorage_deposit_ugnot,
          qstorage_last_successful_height, collected_at
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        ) ON CONFLICT (chain_id, path) DO UPDATE SET
          path_kind=EXCLUDED.path_kind, observed_height=EXCLUDED.observed_height,
          collection_status=EXCLUDED.collection_status, content_sha256=EXCLUDED.content_sha256,
          file_count=EXCLUDED.file_count, gno_file_count=EXCLUDED.gno_file_count,
          test_file_count=EXCLUDED.test_file_count, has_gnomod=EXCLUDED.has_gnomod,
          total_file_bytes=EXCLUDED.total_file_bytes, total_file_lines=EXCLUDED.total_file_lines,
          dependency_count=EXCLUDED.dependency_count,
          source_rpc_endpoint_id=EXCLUDED.source_rpc_endpoint_id,
          qdoc_status=EXCLUDED.qdoc_status, qdoc_summary=EXCLUDED.qdoc_summary,
          qdoc_payload=EXCLUDED.qdoc_payload,
          qdoc_last_successful_height=EXCLUDED.qdoc_last_successful_height,
          qpkg_json_status=EXCLUDED.qpkg_json_status,
          qpkg_json_summary=EXCLUDED.qpkg_json_summary,
          qpkg_json_payload=EXCLUDED.qpkg_json_payload,
          qpkg_json_last_successful_height=EXCLUDED.qpkg_json_last_successful_height,
          qfuncs_status=EXCLUDED.qfuncs_status, qfuncs_summary=EXCLUDED.qfuncs_summary,
          qfuncs_payload=EXCLUDED.qfuncs_payload,
          qfuncs_last_successful_height=EXCLUDED.qfuncs_last_successful_height,
          qrender_status=EXCLUDED.qrender_status, qrender_sha256=EXCLUDED.qrender_sha256,
          qrender_byte_count=EXCLUDED.qrender_byte_count,
          qrender_line_count=EXCLUDED.qrender_line_count,
          qrender_non_empty=EXCLUDED.qrender_non_empty,
          qrender_last_successful_height=EXCLUDED.qrender_last_successful_height,
          qstorage_status=EXCLUDED.qstorage_status, qstorage_bytes=EXCLUDED.qstorage_bytes,
          qstorage_deposit_ugnot=EXCLUDED.qstorage_deposit_ugnot,
          qstorage_last_successful_height=EXCLUDED.qstorage_last_successful_height,
          collected_at=EXCLUDED.collected_at, updated_at=now()""",
        values,
    )
    if not current or current["content_sha256"] != prepared.content_sha256:
        cursor.execute(
            "DELETE FROM realm_metadata_files WHERE chain_id = %s AND path = %s",
            (snapshot.chain_id, snapshot.path),
        )
        for item in prepared.files:
            cursor.execute(
                """INSERT INTO realm_metadata_files (
                  chain_id,path,filename,file_kind,content,byte_count,line_count,sha256,
                  package_declared,import_candidate_count
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    snapshot.chain_id, snapshot.path, item.filename, item.file_kind,
                    item.content, item.byte_count, item.line_count, item.sha256,
                    item.package_declared, item.import_candidate_count,
                ),
            )
            for imported_path, imported_kind in item.imports:
                cursor.execute(
                    """INSERT INTO realm_metadata_imports (
                      chain_id,path,source_filename,imported_path,imported_kind
                    ) VALUES (%s,%s,%s,%s,%s)""",
                    (
                        snapshot.chain_id, snapshot.path, item.filename,
                        imported_path, imported_kind,
                    ),
                )
    return prepared


def publish_metadata_snapshot(connection, snapshot: MetadataSnapshot) -> PreparedSnapshot:
    """Publish atomically without closing the caller-owned Psycopg connection."""
    with connection.transaction():
        with connection.cursor() as cursor:
            return publish_metadata_snapshot_cursor(cursor, snapshot)


def persist_metadata_refresh_state_cursor(cursor, state: MetadataRefreshState) -> None:
    """Validate and monotonically upsert future collector run state."""
    if not isinstance(state.chain_id, str) or not _CHAIN_RE.fullmatch(state.chain_id):
        raise MetadataPersistenceError("invalid_refresh_state")
    if not _strict_int(state.observed_height, minimum=1):
        raise MetadataPersistenceError("invalid_refresh_state")
    if state.run_status not in {"running", "complete", "partial", "failed"}:
        raise MetadataPersistenceError("invalid_refresh_state")
    counts = (
        state.selected_path_count,
        state.published_path_count,
        state.failed_path_count,
    )
    if any(not _strict_int(value) for value in counts) or sum(counts[1:]) > counts[0]:
        raise MetadataPersistenceError("invalid_refresh_state")
    if not _aware(state.started_at):
        raise MetadataPersistenceError("invalid_refresh_state")
    if state.run_status == "running":
        if state.completed_at is not None:
            raise MetadataPersistenceError("invalid_refresh_state")
    elif not _aware(state.completed_at) or state.completed_at < state.started_at:
        raise MetadataPersistenceError("invalid_refresh_state")
    if (state.last_successful_height is None) != (state.last_successful_at is None):
        raise MetadataPersistenceError("invalid_refresh_state")
    if state.last_successful_height is not None and (
        not _strict_int(state.last_successful_height, minimum=1)
        or state.last_successful_height > state.observed_height
        or not _aware(state.last_successful_at)
    ):
        raise MetadataPersistenceError("invalid_refresh_state")
    cursor.execute(
        "SELECT observed_height FROM realm_metadata_refresh_state "
        "WHERE chain_id = %s FOR UPDATE",
        (state.chain_id,),
    )
    current = cursor.fetchone()
    if current is not None and current[0] > state.observed_height:
        raise StaleMetadataSnapshot("stale_metadata_refresh_state")
    cursor.execute(
        """INSERT INTO realm_metadata_refresh_state (
          chain_id,observed_height,run_status,selected_path_count,published_path_count,
          failed_path_count,started_at,completed_at,last_successful_height,last_successful_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (chain_id) DO UPDATE SET
          observed_height=EXCLUDED.observed_height, run_status=EXCLUDED.run_status,
          selected_path_count=EXCLUDED.selected_path_count,
          published_path_count=EXCLUDED.published_path_count,
          failed_path_count=EXCLUDED.failed_path_count, started_at=EXCLUDED.started_at,
          completed_at=EXCLUDED.completed_at,
          last_successful_height=EXCLUDED.last_successful_height,
          last_successful_at=EXCLUDED.last_successful_at, updated_at=now()""",
        (
            state.chain_id, state.observed_height, state.run_status,
            *counts, state.started_at, state.completed_at,
            state.last_successful_height, state.last_successful_at,
        ),
    )
