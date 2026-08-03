"""Bounded extraction and aggregation of Gno Realm catalog observations."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .transaction_summary import MAX_MESSAGES

_PATH_RE = re.compile(r"^gno\.land/(?P<kind>[rp])/[!-\.0-~]+(?:/[!-\.0-~]+)*$")
_ADDRESS_RE = re.compile(r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")


def path_kind(path: Any) -> str | None:
    """Return the catalog kind for a bounded canonical path, otherwise ``None``."""
    if not isinstance(path, str) or not 1 <= len(path) <= 256:
        return None
    if any(character.isspace() for character in path) or "?" in path or "#" in path:
        return None
    match = _PATH_RE.fullmatch(path)
    return {"r": "realm", "p": "package"}.get(match.group("kind")) if match else None


@dataclass(frozen=True, slots=True)
class RealmObservation:
    path: str
    kind: str
    message_index: int
    observation_type: str
    sender: str | None


def extract_observations(payload_summary: Any) -> tuple[RealmObservation, ...]:
    """Inspect only normalized summary fields and return at most twenty observations."""
    if not isinstance(payload_summary, dict) or payload_summary.get("parse_status") != "parsed":
        return ()
    messages = payload_summary.get("messages")
    if not isinstance(messages, list):
        return ()
    result = []
    for index, message in enumerate(messages[:MAX_MESSAGES]):
        if not isinstance(message, dict):
            continue
        message_type = message.get("type")
        path = message.get("package_path")
        kind = path_kind(path)
        sender = message.get("sender")
        sender = sender if isinstance(sender, str) and _ADDRESS_RE.fullmatch(sender) else None
        if message_type == "gno.vm.MsgAddPackage" and kind:
            result.append(RealmObservation(path, kind, index, "deployment", sender))
        elif message_type == "gno.vm.MsgCall" and kind == "realm":
            result.append(RealmObservation(path, kind, index, "call", sender))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PathAggregate:
    path: str
    kind: str
    first_tx_index: int
    deploy_tx_index: int | None
    deployer_address: str | None
    last_activity_tx_index: int | None
    call_count: int
    successful_call_count: int
    failed_call_count: int
    unknown_result_call_count: int


def aggregate_block(transactions: Iterable[tuple[int, Any, str | None]]) -> tuple[PathAggregate, ...]:
    """Aggregate observations to one immutable value per path for a complete block."""
    values: dict[str, dict[str, Any]] = {}
    for tx_index, summary, status in transactions:
        for observation in extract_observations(summary):
            value = values.setdefault(observation.path, {"kind": observation.kind, "first": tx_index,
                "deploy": None, "deployer": None, "last": None, "success": 0, "failed": 0, "unknown": 0})
            value["first"] = min(value["first"], tx_index)
            if observation.observation_type == "deployment" and (value["deploy"] is None or tx_index < value["deploy"]):
                value["deploy"], value["deployer"] = tx_index, observation.sender
            elif observation.observation_type == "call":
                value["last"] = tx_index if value["last"] is None else max(value["last"], tx_index)
                value[status if status in ("success", "failed") else "unknown"] += 1
    return tuple(PathAggregate(path, value["kind"], value["first"], value["deploy"], value["deployer"],
        value["last"], value["success"] + value["failed"] + value["unknown"], value["success"],
        value["failed"], value["unknown"]) for path, value in sorted(values.items()))


def parse_qpaths(payload: bytes | str) -> tuple[tuple[str, str], ...]:
    """Validate, deduplicate and bound one qpaths response atomically."""
    if isinstance(payload, bytes):
        if len(payload) > 2_570_000:
            raise ValueError("qpaths_too_large")
        try:
            payload = payload.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("qpaths_invalid_utf8") from exc
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > 2_570_000:
        raise ValueError("qpaths_too_large")
    paths: dict[str, str] = {}
    for raw_path in payload.splitlines():
        if not raw_path:
            continue
        kind = path_kind(raw_path)
        if kind is None:
            raise ValueError("qpaths_invalid_path")
        paths[raw_path] = kind
        if len(paths) > 10_000:
            raise ValueError("qpaths_too_many_paths")
    if not paths:
        raise ValueError("qpaths_empty")
    return tuple(sorted(paths.items()))
