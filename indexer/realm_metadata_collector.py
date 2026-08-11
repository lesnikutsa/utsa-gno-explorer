"""One-shot, fixed-height Realm and Package metadata collection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from scripts.inspect_rpc import RpcError

from .realm_metadata import (
    MetadataParseError,
    parse_qdoc,
    parse_qfile_listing,
    parse_qfuncs,
    parse_qpkg_json,
    parse_qstorage,
    summarize_qrender,
)
from .realm_metadata_persistence import (
    JsonCapability,
    MetadataFile,
    MetadataSnapshot,
    RenderCapability,
    StorageCapability,
)

PathKind = Literal["realm", "package"]


@dataclass(frozen=True)
class CollectionRequest:
    chain_id: str
    path: str
    path_kind: PathKind
    observed_height: int
    source_rpc_endpoint_id: int | None = None


@dataclass(frozen=True)
class PathCollectionResult:
    path: str
    path_kind: PathKind
    observed_height: int
    status: Literal["complete", "partial", "failed"]
    snapshot: MetadataSnapshot | None = None
    failure_code: str | None = None

    @property
    def publishable(self) -> bool:
        return self.snapshot is not None


def _rpc_status(exc: RpcError) -> str:
    """Map RPC failures to the only persistence statuses exposed by a run."""
    message = str(exc)
    if message == "ABCI query returned an application error":
        return "application_error"
    if message in {
        "Malformed ABCI response",
        "Malformed or oversized ABCI response data",
        "Malformed ABCI response data",
        "ABCI response exceeds size limit",
        "ABCI response data is not UTF-8",
    }:
        return "invalid_response"
    return "rpc_error"


def _json_capability(client, rpc_path: str, data: str, height: int,
                     parser: Callable[[str], object]) -> JsonCapability:
    try:
        payload = client.abci_query(rpc_path, data, height)
        parser(payload)
        return JsonCapability("ok", payload)
    except (MetadataParseError, UnicodeError):
        return JsonCapability("invalid_response")
    except RpcError as exc:
        return JsonCapability(_rpc_status(exc))


def _render_capability(client, path: str, height: int) -> RenderCapability:
    try:
        # Keep the body local only until its bounded summary has been constructed.
        summary = summarize_qrender(client.abci_query("vm/qrender", f"{path}:", height))
        return RenderCapability("ok", summary["sha256"], summary["byte_count"],
                                summary["line_count"], summary["non_empty"])
    except (MetadataParseError, UnicodeError):
        return RenderCapability("invalid_response")
    except RpcError as exc:
        return RenderCapability(_rpc_status(exc))


def _storage_capability(client, path: str, height: int) -> StorageCapability:
    try:
        summary = parse_qstorage(client.abci_query("vm/qstorage", path, height))
        return StorageCapability("ok", summary["storage_bytes"], summary["deposit_ugnot"])
    except (MetadataParseError, UnicodeError):
        return StorageCapability("invalid_response")
    except RpcError as exc:
        return StorageCapability(_rpc_status(exc))


def collect_path_metadata(client, request: CollectionRequest, *,
                          collected_at: datetime | None = None) -> PathCollectionResult:
    """Collect one complete required file snapshot and bounded capabilities."""
    try:
        listing_payload = client.abci_query("vm/qfile", request.path, request.observed_height)
        listing = parse_qfile_listing(listing_payload)
    except (MetadataParseError, UnicodeError, RpcError):
        return PathCollectionResult(request.path, request.path_kind,
                                    request.observed_height, "failed", failure_code="qfile_listing")

    files: list[MetadataFile] = []
    for filename in listing["filenames"]:
        try:
            content = client.abci_query(
                "vm/qfile", f"{request.path}/{filename}", request.observed_height
            )
            # Reject non-text and unsafe UTF-8 before any optional work or publication.
            if not isinstance(content, str):
                raise MetadataParseError("invalid_payload_type")
            content.encode("utf-8", "strict")
            files.append(MetadataFile(filename, content))
        except (MetadataParseError, UnicodeEncodeError, RpcError):
            return PathCollectionResult(request.path, request.path_kind,
                                        request.observed_height, "failed", failure_code="qfile_file")

    qdoc = _json_capability(
        client, "vm/qdoc", request.path, request.observed_height,
        lambda payload: parse_qdoc(payload, requested_path=request.path),
    )
    qpkg_json = _json_capability(
        client, "vm/qpkg_json", request.path, request.observed_height, parse_qpkg_json
    )
    qfuncs = _json_capability(
        client, "vm/qfuncs", request.path, request.observed_height, parse_qfuncs
    )
    if request.path_kind == "realm":
        qrender = _render_capability(client, request.path, request.observed_height)
        qstorage = _storage_capability(client, request.path, request.observed_height)
        applicable = (qdoc, qpkg_json, qfuncs, qrender, qstorage)
    else:
        qrender = RenderCapability("not_applicable")
        qstorage = StorageCapability("not_applicable")
        applicable = (qdoc, qpkg_json, qfuncs)
    status = "complete" if all(item.status == "ok" for item in applicable) else "partial"
    snapshot = MetadataSnapshot(
        chain_id=request.chain_id,
        path=request.path,
        path_kind=request.path_kind,
        observed_height=request.observed_height,
        collection_status=status,
        expected_filenames=tuple(listing["filenames"]),
        files=tuple(files),
        collected_at=collected_at or datetime.now(timezone.utc),
        source_rpc_endpoint_id=request.source_rpc_endpoint_id,
        qdoc=qdoc,
        qpkg_json=qpkg_json,
        qfuncs=qfuncs,
        qrender=qrender,
        qstorage=qstorage,
    )
    return PathCollectionResult(request.path, request.path_kind,
                                request.observed_height, status, snapshot)
