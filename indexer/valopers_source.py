"""Bounded, read-only access to the Valopers realm through vm/qrender."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from scripts.inspect_rpc import GnoRpcClient, RpcError

VALOPERS_RENDER_PREFIX = "gno.land/r/gnops/valopers:"
MAX_DECODED_RESPONSE_BYTES = 1024 * 1024
MAX_ENCODED_RESPONSE_CHARS = 4 * ((MAX_DECODED_RESPONSE_BYTES + 2) // 3)
MAX_PREVIEW_CHARS = 160
MAX_PAGE_NUMBER = 1_000_000

_PAGE_QUERY_RE = re.compile(r"\?page=([1-9][0-9]*)\Z")
_OPERATOR_ADDRESS_RE = re.compile(r"g1[023456789ac-hj-np-z]{38}\Z")


@dataclass(frozen=True)
class ValopersRenderResult:
    """Validated metadata and bounded display output for one qrender response."""

    query_kind: str
    source_height: int
    response_height: int
    decoded_byte_count: int
    sha256: str
    preview: str


def build_root_render_data() -> str:
    return VALOPERS_RENDER_PREFIX


def build_page_render_data(page_query: str) -> str:
    match = _PAGE_QUERY_RE.fullmatch(page_query)
    if not match or int(match.group(1)) > MAX_PAGE_NUMBER:
        raise RpcError(f"Page query must have the form ?page=N, where N is 1-{MAX_PAGE_NUMBER}")
    return f"{VALOPERS_RENDER_PREFIX}{page_query}"


def build_detail_render_data(operator_address: str) -> str:
    if not _OPERATOR_ADDRESS_RE.fullmatch(operator_address):
        raise RpcError("Operator address must be a 40-character lowercase g1 Bech32 address")
    return f"{VALOPERS_RENDER_PREFIX}{operator_address}"


def build_qrender_params(render_data: str, source_height: int) -> dict[str, Any]:
    if not isinstance(source_height, int) or isinstance(source_height, bool) or source_height < 1:
        raise RpcError("Pinned source height must be a positive integer")
    encoded_data = base64.b64encode(render_data.encode("utf-8")).decode("ascii")
    return {
        "path": json.dumps("vm/qrender"),
        "data": json.dumps(encoded_data),
        "height": source_height,
        "prove": "false",
    }


def bounded_preview(decoded: str, max_chars: int = MAX_PREVIEW_CHARS) -> str:
    if max_chars < 0:
        raise ValueError("max_chars must not be negative")
    parts: list[str] = []
    length = 0
    for character in decoded:
        if character == "\n":
            replacement = r"\n"
        elif character == "\r":
            replacement = r"\r"
        elif character == "\t":
            replacement = r"\t"
        elif unicodedata.category(character).startswith("C"):
            replacement = f"\\u{ord(character):04x}"
        else:
            replacement = character
        remaining = max_chars - length
        if remaining <= 0:
            break
        parts.append(replacement[:remaining])
        length += min(len(replacement), remaining)
    return "".join(parts)


def decode_qrender_response(
    payload: dict[str, Any], query_kind: str, source_height: int
) -> ValopersRenderResult:
    result = payload.get("result") if isinstance(payload, dict) else None
    response = result.get("response") if isinstance(result, dict) else None
    if not isinstance(response, dict):
        raise RpcError("Malformed qrender response: missing result.response")

    raw_height = response.get("Height")
    if not isinstance(raw_height, int) or isinstance(raw_height, bool) or raw_height < 1:
        raise RpcError("Malformed qrender response: invalid result.response.Height")
    response_height = raw_height
    if response_height != source_height:
        raise RpcError(
            f"Qrender response height mismatch: expected {source_height}, got {response_height}"
        )

    response_base = response.get("ResponseBase")
    if not isinstance(response_base, dict):
        raise RpcError("Malformed qrender response: missing result.response.ResponseBase")
    if "Error" not in response_base or response_base["Error"] not in (None, ""):
        raise RpcError("Qrender ABCI response reported an error")

    encoded = response_base.get("Data")
    if not isinstance(encoded, str) or not encoded:
        raise RpcError("Malformed qrender response: missing result.response.ResponseBase.Data")
    if len(encoded) > MAX_ENCODED_RESPONSE_CHARS:
        raise RpcError("Qrender response exceeds encoded response size limit")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RpcError(
            "Malformed qrender response: invalid base64 in result.response.ResponseBase.Data"
        ) from exc
    if len(decoded) > MAX_DECODED_RESPONSE_BYTES:
        raise RpcError("Qrender response exceeds decoded response size limit")
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RpcError(
            "Malformed qrender response: decoded result.response.ResponseBase.Data is not UTF-8"
        ) from exc

    return ValopersRenderResult(
        query_kind=query_kind,
        source_height=source_height,
        response_height=response_height,
        decoded_byte_count=len(decoded),
        sha256=hashlib.sha256(decoded).hexdigest(),
        preview=bounded_preview(text),
    )


def fetch_render(
    client: GnoRpcClient, render_data: str, query_kind: str, source_height: int
) -> ValopersRenderResult:
    payload = client.get("abci_query", **build_qrender_params(render_data, source_height))
    return decode_qrender_response(payload, query_kind, source_height)
