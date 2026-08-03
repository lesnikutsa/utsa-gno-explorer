"""Bounded, chain-neutral transaction summary contract."""
from __future__ import annotations

import json
import math
from typing import Any, Literal, TypedDict

SCHEMA_VERSION = 1
MAX_MESSAGES = 20
MAX_LABEL_LENGTH = 80
MAX_TYPE_LENGTH = 160
MAX_TOKEN_LENGTH = 64
MAX_MESSAGE_FIELDS = 17
MAX_VALUE_LENGTH = 160
MAX_PACKAGE_PATH_LENGTH = 256
MAX_SUMMARY_BYTES = 16_384
MAX_INTEGER_BITS = 256
MAX_MESSAGE_COUNT = 100_000

ParseStatus = Literal["unparsed", "parsed", "unsupported", "invalid"]
PARSE_STATUSES = frozenset({"unparsed", "parsed", "unsupported", "invalid"})
_REQUIRED_FIELDS = frozenset({"schema_version", "chain_family", "parse_status", "message_count", "messages_truncated", "primary", "messages"})
_REQUIRED_PRIMARY_FIELDS = frozenset({"type", "category", "action", "label"})
_FORBIDDEN_KEY_PARTS = ("base64", "signature", "raw_transaction", "raw_tx", "decoded_bytes")


class PrimarySummary(TypedDict):
    type: str
    category: str
    action: str
    label: str


class TransactionSummary(TypedDict):
    schema_version: int
    chain_family: str
    parse_status: ParseStatus
    message_count: int | None
    messages_truncated: bool
    primary: PrimarySummary
    messages: list[dict[str, str | int | float | bool | None]]


def generic_summary(parse_status: ParseStatus = "unparsed") -> TransactionSummary:
    """Return the safe fallback used until an application adapter is available."""
    if parse_status not in PARSE_STATUSES:
        parse_status = "unparsed"
    return {
        "schema_version": SCHEMA_VERSION,
        "chain_family": "unknown",
        "parse_status": parse_status,
        "message_count": None,
        "messages_truncated": False,
        "primary": {
            "type": "unknown",
            "category": "unknown",
            "action": "unknown",
            "label": "Transaction",
        },
        "messages": [],
    }


def normalize_summary(candidate: Any, fallback_status: ParseStatus = "unparsed") -> TransactionSummary:
    """Normalize adapter output, or safely discard it when its shape is malformed."""
    try:
        if not isinstance(candidate, dict) or not _REQUIRED_FIELDS <= candidate.keys():
            raise ValueError("missing summary fields")
        if candidate["schema_version"] != SCHEMA_VERSION or candidate["parse_status"] not in PARSE_STATUSES:
            raise ValueError("unsupported summary version or status")
        if not isinstance(candidate["messages_truncated"], bool):
            raise ValueError("invalid truncation marker")
        count = candidate["message_count"]
        if count is not None and (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= MAX_MESSAGE_COUNT
        ):
            raise ValueError("invalid message count")
        primary = candidate["primary"]
        if not isinstance(primary, dict) or not _REQUIRED_PRIMARY_FIELDS <= primary.keys():
            raise ValueError("invalid primary summary")
        messages = candidate["messages"]
        if not isinstance(messages, list):
            raise ValueError("invalid messages")
        if count is not None and count < len(messages):
            raise ValueError("message count is smaller than supplied messages")

        normalized_messages = [_normalize_message(message) for message in messages[:MAX_MESSAGES]]
        normalized: TransactionSummary = {
            "schema_version": SCHEMA_VERSION,
            "chain_family": _text(candidate["chain_family"], MAX_TOKEN_LENGTH),
            "parse_status": candidate["parse_status"],
            "message_count": count,
            "messages_truncated": (
                candidate["messages_truncated"]
                or len(messages) > MAX_MESSAGES
                or (count is not None and count > len(normalized_messages))
            ),
            "primary": {
                "type": _text(primary["type"], MAX_TYPE_LENGTH),
                "category": _text(primary["category"], MAX_TOKEN_LENGTH),
                "action": _text(primary["action"], MAX_TOKEN_LENGTH),
                "label": _text(primary["label"], MAX_LABEL_LENGTH),
            },
            "messages": normalized_messages,
        }
        while normalized["messages"] and summary_size_bytes(normalized) > MAX_SUMMARY_BYTES:
            normalized["messages"].pop()
            normalized["messages_truncated"] = True
        if summary_size_bytes(normalized) > MAX_SUMMARY_BYTES:
            raise ValueError("summary exceeds total size limit")
        return normalized
    except (KeyError, TypeError, ValueError):
        return generic_summary(fallback_status)


def _normalize_message(message: Any) -> dict[str, str | int | float | bool | None]:
    if not isinstance(message, dict) or len(message) > MAX_MESSAGE_FIELDS:
        raise ValueError("invalid message summary")
    result: dict[str, str | int | float | bool | None] = {}
    for key, value in message.items():
        if not isinstance(key, str) or any(part in key.lower() for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError("unsafe message field")
        safe_key = _text(key, MAX_TOKEN_LENGTH)
        if safe_key in result:
            raise ValueError("message keys collide after normalization")
        if isinstance(value, str):
            limit = (MAX_TYPE_LENGTH if safe_key == "type" else
                     MAX_LABEL_LENGTH if safe_key == "label" else
                     MAX_PACKAGE_PATH_LENGTH if safe_key == "package_path" else
                     MAX_VALUE_LENGTH)
            normalized_value = _text(value, limit)
            if (safe_key == "package_path"
                    and message.get("package_path_complete") is True
                    and normalized_value != value):
                raise ValueError("complete package path must not be altered")
            result[safe_key] = normalized_value
        elif value is None or isinstance(value, bool):
            result[safe_key] = value
        elif isinstance(value, int):
            if abs(value).bit_length() > MAX_INTEGER_BITS:
                raise ValueError("message integer exceeds size limit")
            result[safe_key] = value
        elif isinstance(value, float) and math.isfinite(value):
            result[safe_key] = value
        else:
            raise ValueError("message values must be JSON-safe scalars")
    if "package_path_complete" in message:
        marker = message["package_path_complete"]
        if not isinstance(marker, bool) or "package_path" not in result:
            raise ValueError("invalid package path completeness marker")
    return result


def summary_size_bytes(summary: Any) -> int:
    """Return the deterministic compact UTF-8 JSON size of a summary."""
    return len(json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8"))


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("summary text must be a string")
    printable = "".join(character for character in value.strip() if character.isprintable())
    if not printable:
        raise ValueError("summary text must not be empty")
    return printable[:limit]
