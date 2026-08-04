"""Bounded extraction and aggregation of Gno Realm catalog observations."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .transaction_summary import MAX_MESSAGES

_PATH_RE = re.compile(r"^gno\.land/(?P<kind>[rp])/[!-\.0-~]+(?:/[!-\.0-~]+)*$")
_ADDRESS_RE = re.compile(r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")


def is_complete_package_path(message: Any, path: Any) -> bool:
    """Accept current completeness markers and the bounded legacy convention."""
    if not isinstance(message, dict):
        return False
    completeness = message.get("package_path_complete")
    return completeness is True or (
        completeness is None and isinstance(path, str) and len(path) < 160
    )


def path_kind(path: Any) -> str | None:
    """Return the catalog kind for a bounded canonical path, otherwise ``None``."""
    if not isinstance(path, str) or not 1 <= len(path) <= 256:
        return None
    if any(character.isspace() for character in path) or "?" in path or "#" in path:
        return None
    match = _PATH_RE.fullmatch(path)
    return {"r": "realm", "p": "package"}.get(match.group("kind")) if match else None


def namespace_key(path: Any) -> str | None:
    """Return the exact first segment of a canonical Realm path."""
    if path_kind(path) != "realm":
        return None
    return path.split("/", 3)[2]


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
        if not is_complete_package_path(message, path):
            continue
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

@dataclass(frozen=True, slots=True)
class RealmCallRecord:
    """One compact locator extracted from a normalized MsgCall summary."""
    path: str
    message_index: int
    caller_address: str | None
    function_name: str | None
    args_count: int | None
    send_amount: str | None


def extract_realm_calls(payload_summary: Any) -> tuple[RealmCallRecord, ...]:
    """Fail closed while extracting bounded, complete Realm MsgCall locators."""
    if not isinstance(payload_summary, dict) or payload_summary.get("parse_status") != "parsed":
        return ()
    messages = payload_summary.get("messages")
    if not isinstance(messages, list):
        return ()
    calls: list[RealmCallRecord] = []
    for index, message in enumerate(messages[:MAX_MESSAGES]):
        if not isinstance(message, dict) or message.get("type") != "gno.vm.MsgCall":
            continue
        path = message.get("package_path")
        if not is_complete_package_path(message, path) or path_kind(path) != "realm":
            continue
        caller = message.get("sender")
        function = message.get("function")
        args_count = message.get("args_count")
        send = message.get("send")
        if caller is not None and (not isinstance(caller, str) or _ADDRESS_RE.fullmatch(caller) is None):
            continue
        if function is not None and (not isinstance(function, str) or not function or len(function) > 160):
            continue
        if (args_count is not None and (isinstance(args_count, bool) or not isinstance(args_count, int)
                                       or not 0 <= args_count <= 100_000)):
            continue
        if send is not None and (not isinstance(send, str) or not send or len(send) > 160):
            continue
        calls.append(RealmCallRecord(path, index, caller, function, args_count, send))
    return tuple(calls)
