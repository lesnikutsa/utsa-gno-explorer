"""Strict, pure parsers for the rendered Valopers Markdown contract."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_RENDER_CHARS = 1024 * 1024
MAX_RENDER_BYTES = 1024 * 1024
MAX_DESCRIPTION_CHARS = 100_000

_MONIKER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 _-]{0,30}[A-Za-z0-9])?\Z")
_ADDRESS_PATTERN = r"g1[023456789ac-hj-np-z]{38}"
_ADDRESS_RE = re.compile(_ADDRESS_PATTERN + r"\Z")
_GPUB_RE = re.compile(r"gpub1[023456789ac-hj-np-z]{5,195}\Z")
_ENTRY_RE = re.compile(
    rf" \* \[(?P<moniker>[^\]\r\n]+)\]\(/r/gnops/valopers:(?P<detail>{_ADDRESS_PATTERN})\)"
    rf" - \[profile\]\(/r/demo/profile:u/(?P<profile>{_ADDRESS_PATTERN})\)\Z"
)
_ENTRY_CANDIDATE_RE = re.compile(r" \* \[")
_DETAIL_TAIL_RE = re.compile(
    rf"\n\n- Operator Address: (?P<operator>{_ADDRESS_PATTERN})"
    rf"\n- Signing Address: (?P<signing>{_ADDRESS_PATTERN})"
    r"\n- Signing PubKey: (?P<pubkey>[^\r\n]+)"
    r"\n- Server Type: (?P<server>[^\r\n]+)"
    rf"\n\n\[Profile link\]\(/r/demo/profile:u/(?P<profile>{_ADDRESS_PATTERN})\)\n?\Z"
)


@dataclass(frozen=True)
class ValoperListEntry:
    moniker: str
    operator_address: str


@dataclass(frozen=True)
class ValoperProfile:
    moniker: str
    description: str
    operator_address: str
    signing_address: str
    signing_pubkey: str
    server_type: str
    profile_path: str


def _validate_render(rendered_text: str) -> None:
    if not isinstance(rendered_text, str):
        raise TypeError("rendered_text must be a string")
    if len(rendered_text) > MAX_RENDER_CHARS or len(rendered_text.encode("utf-8")) > MAX_RENDER_BYTES:
        raise ValueError("Valopers render exceeds the input size limit")


def _validate_moniker(moniker: str) -> None:
    if not _MONIKER_RE.fullmatch(moniker):
        raise ValueError("Invalid Valoper moniker")


def parse_valopers_list(rendered_text: str) -> tuple[ValoperListEntry, ...]:
    """Parse canonical entries while ignoring non-entry instructions and pager text."""
    _validate_render(rendered_text)
    entries: list[ValoperListEntry] = []
    seen: set[str] = set()
    for line in rendered_text.splitlines():
        match = _ENTRY_RE.fullmatch(line)
        if match is None:
            if _ENTRY_CANDIDATE_RE.match(line):
                raise ValueError("Malformed Valopers list entry")
            continue
        moniker = match.group("moniker")
        operator = match.group("detail")
        _validate_moniker(moniker)
        if match.group("profile") != operator:
            raise ValueError("Valopers entry addresses do not match")
        if operator in seen:
            raise ValueError("Duplicate Valoper operator address")
        seen.add(operator)
        entries.append(ValoperListEntry(moniker, operator))

    if not entries and "No valopers to display." not in rendered_text.splitlines():
        raise ValueError("Valopers list contains no canonical entries")
    return tuple(entries)


def parse_valoper_detail(rendered_text: str) -> ValoperProfile:
    """Parse identity fields only from the canonical block anchored at the document end."""
    _validate_render(rendered_text)
    prefix = "Valoper's details:\n## "
    if not rendered_text.startswith(prefix):
        raise ValueError("Invalid Valoper detail document prefix")

    heading_end = rendered_text.find("\n", len(prefix))
    if heading_end < 0:
        raise ValueError("Missing Valoper detail body")
    moniker = rendered_text[len(prefix):heading_end]
    _validate_moniker(moniker)

    tail = _DETAIL_TAIL_RE.search(rendered_text, heading_end)
    if tail is None:
        raise ValueError("Malformed Valoper detail field block")
    description = rendered_text[heading_end + 1:tail.start()]
    if not description:
        raise ValueError("Valoper description must not be empty")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ValueError("Valoper description exceeds the size limit")

    operator = tail.group("operator")
    signing = tail.group("signing")
    pubkey = tail.group("pubkey")
    server = tail.group("server")
    if not _ADDRESS_RE.fullmatch(operator) or not _ADDRESS_RE.fullmatch(signing):
        raise ValueError("Invalid Valoper address")
    if not _GPUB_RE.fullmatch(pubkey):
        raise ValueError("Invalid Valoper signing public key")
    if server not in {"cloud", "on-prem", "data-center"}:
        raise ValueError("Invalid Valoper server type")
    if tail.group("profile") != operator:
        raise ValueError("Valoper profile address does not match operator address")

    return ValoperProfile(
        moniker=moniker,
        description=description,
        operator_address=operator,
        signing_address=signing,
        signing_pubkey=pubkey,
        server_type=server,
        profile_path=f"/r/demo/profile:u/{operator}",
    )
