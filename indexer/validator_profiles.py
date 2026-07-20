"""Bounded one-shot synchronization of official Valopers render output."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter, deque
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from scripts.inspect_rpc import result, to_int

DEFAULT_REALM = "gno.land/r/gnops/valopers"
MAX_PAGES = 20
MAX_PROFILES = 500
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_MONIKER = 32
MAX_DESCRIPTION = 2048
MAX_ADDRESS = 128
MAX_GPUB = 512
MAX_SOURCE_PATH = 512
SERVER_TYPES = frozenset({"cloud", "on-prem", "data-center"})
SUPPORTED_KEY_LENGTHS = {"/tm.PubKeyEd25519": 32, "/tm.PubKeySecp256k1": 33}


class ProfileSourceError(RuntimeError):
    """Raised when a source snapshot is incomplete, malformed, or inconsistent."""


@dataclass(frozen=True)
class SourceResponse:
    text: str
    height: int


@dataclass(frozen=True)
class ValidatorProfile:
    operator_address: str
    moniker: str
    description: str
    server_type: str
    keep_running: bool | None
    consensus_pubkey: str
    source_signing_address: str
    source_realm: str
    source_profile_path: str
    source_height: int
    profile_hash: str
    normalized_public_key_type: str | None = None
    normalized_public_key_value: str | None = None
    signing_address: str | None = None
    match_status: str = "invalid_pubkey"


@dataclass(frozen=True)
class SyncResult:
    source_height: int
    profiles: tuple[ValidatorProfile, ...]


def _bech32_polymod(values: Iterable[int]) -> int:
    checksum = 1
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _convert_bits(values: Iterable[int], from_bits: int, to_bits: int) -> bytes:
    accumulator = bits = 0
    output = bytearray()
    maximum = (1 << to_bits) - 1
    for value in values:
        if value < 0 or value >> from_bits:
            raise ValueError("invalid bech32 word")
        accumulator = (accumulator << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            output.append((accumulator >> bits) & maximum)
    if bits >= from_bits or ((accumulator << (to_bits - bits)) & maximum):
        raise ValueError("invalid bech32 padding")
    return bytes(output)


def _varint(payload: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    for _ in range(10):
        if offset >= len(payload):
            raise ValueError("truncated varint")
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            if shift and byte == 0:
                raise ValueError("non-canonical varint")
            return value, offset
        shift += 7
    raise ValueError("invalid varint")


def _length_field(payload: bytes, offset: int, expected_tag: int) -> tuple[bytes, int]:
    tag, offset = _varint(payload, offset)
    if tag != expected_tag:
        raise ValueError("unexpected Amino field")
    length, offset = _varint(payload, offset)
    end = offset + length
    if end > len(payload):
        raise ValueError("truncated Amino field")
    return payload[offset:end], end


def normalize_gpub(value: str) -> tuple[str, str]:
    """Decode Gno Bech32 containing an Amino-encoded public-key interface."""
    if not isinstance(value, str) or not value or value != value.lower():
        raise ValueError("gpub must be lowercase")
    separator = value.rfind("1")
    if separator <= 0 or value[:separator] != "gpub" or len(value) - separator < 7:
        raise ValueError("wrong gpub HRP or length")
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    try:
        words = [charset.index(character) for character in value[separator + 1:]]
    except ValueError as exc:
        raise ValueError("invalid bech32 character") from exc
    hrp_words = [ord(character) >> 5 for character in "gpub"] + [0] + [ord(character) & 31 for character in "gpub"]
    if _bech32_polymod(hrp_words + words) != 1:
        raise ValueError("invalid bech32 checksum")
    amino = _convert_bits(words[:-6], 5, 8)
    type_bytes, offset = _length_field(amino, 0, 0x0A)
    try:
        key_type = type_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("non-ASCII public key type URL") from exc
    expected_length = SUPPORTED_KEY_LENGTHS.get(key_type)
    if expected_length is None:
        raise ValueError("unsupported public key type URL")
    concrete, offset = _length_field(amino, offset, 0x12)
    if offset != len(amino):
        raise ValueError("trailing Amino data")
    raw_key, nested_offset = _length_field(concrete, 0, 0x0A)
    if nested_offset != len(concrete) or len(raw_key) != expected_length:
        raise ValueError("invalid concrete public key")
    return key_type, base64.b64encode(raw_key).decode("ascii")


def _bounded_text(text: str) -> None:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ProfileSourceError("Valopers response is malformed or oversized")


def _realm_route(realm: str) -> str:
    if realm != DEFAULT_REALM:
        raise ProfileSourceError("unexpected Valopers realm")
    return "/r/" + realm.split("/r/", 1)[1]


def parse_list_page(text: str, realm: str = DEFAULT_REALM) -> tuple[list[str], tuple[str, ...]]:
    """Parse current renderHome profile rows and page.Picker realm links."""
    _bounded_text(text)
    route = _realm_route(realm)
    links = re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", text)
    operators: list[str] = []
    pages: set[str] = set()
    for link in links:
        if link.startswith(route + ":"):
            render_path = link[len(route) + 1:]
            if re.fullmatch(r"g1[0-9a-z]+", render_path):
                if render_path not in operators:
                    operators.append(render_path)
            elif render_path.startswith("?"):
                pages.add(render_path)
            elif render_path:
                raise ProfileSourceError("unexpected Valopers realm render path")
        elif "/r/gnops/valopers" in link:
            raise ProfileSourceError("malformed Valopers realm link")
    if not operators:
        raise ProfileSourceError("Valopers list page has no profile rows")
    return operators, tuple(sorted(pages))


_METADATA = re.compile(r"(?m)^- (Operator Address|Signing Address|Signing PubKey|Server Type):[ \t]*(.*)$")


def parse_detail(text: str, expected_operator: str, height: int, realm: str = DEFAULT_REALM) -> ValidatorProfile:
    """Parse the current `Valoper.Render` Markdown contract exactly."""
    _bounded_text(text)
    _realm_route(realm)
    heading = re.search(r"(?m)^##[ \t]+(.+?)[ \t]*$", text)
    metadata = list(_METADATA.finditer(text))
    if not heading or not metadata or metadata[0].start() <= heading.end():
        raise ProfileSourceError("malformed Valopers detail layout")
    moniker = heading.group(1).strip()
    description = text[heading.end():metadata[0].start()].strip("\n")
    fields: dict[str, str] = {}
    for match in metadata:
        name, field_value = match.group(1), match.group(2).strip()
        if name in fields:
            raise ProfileSourceError("duplicate required profile metadata")
        fields[name] = field_value
    required = ("Operator Address", "Signing Address", "Signing PubKey", "Server Type")
    if any(not fields.get(name) for name in required):
        raise ProfileSourceError("missing required profile metadata")
    operator = fields["Operator Address"]
    source_signing = fields["Signing Address"]
    pubkey = fields["Signing PubKey"]
    server_type = fields["Server Type"]
    if operator != expected_operator:
        raise ProfileSourceError("detail Operator Address does not match list link")
    if not (1 <= len(moniker) <= MAX_MONIKER) or len(description) > MAX_DESCRIPTION:
        raise ProfileSourceError("profile text exceeds Valopers contract bounds")
    if server_type not in SERVER_TYPES:
        raise ProfileSourceError("invalid Valopers Server Type")
    if any(len(address) > MAX_ADDRESS or not re.fullmatch(r"g1[0-9a-z]+", address) for address in (operator, source_signing)):
        raise ProfileSourceError("invalid profile address")
    source_path = f"/r/{realm.split('/r/', 1)[1]}:{operator}"
    if len(pubkey) > MAX_GPUB or len(source_path) > MAX_SOURCE_PATH:
        raise ProfileSourceError("profile key or source path exceeds bounds")
    canonical = json.dumps([operator, moniker, description, server_type, None, pubkey, source_signing], ensure_ascii=False, separators=(",", ":"))
    return ValidatorProfile(operator, moniker, description, server_type, None, pubkey,
                            source_signing, realm, source_path, height,
                            hashlib.sha256(canonical.encode()).hexdigest())


def decode_vm_response(payload: dict, expected_height: int) -> SourceResponse:
    response = result(payload).get("response")
    if not isinstance(response, dict) or to_int(response.get("height")) != expected_height:
        raise ProfileSourceError("malformed or mismatched-height ABCI query response")
    try:
        text = base64.b64decode(response.get("value"), validate=True).decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ProfileSourceError("malformed VM query value") from exc
    _bounded_text(text)
    return SourceResponse(text, expected_height)


def query_render(client, render_path: str, height: int) -> SourceResponse:
    payload = client.get("abci_query", path=json.dumps("vm/qrender"),
                         data=json.dumps(f"{DEFAULT_REALM}:{render_path}"),
                         height=height, prove="false")
    return decode_vm_response(payload, height)


def collect_profiles(client, height: int, realm: str = DEFAULT_REALM,
                     query: Callable[[object, str, int], SourceResponse] = query_render) -> SyncResult:
    _realm_route(realm)
    pending = deque([""])
    seen_pages: set[str] = set()
    operators: list[str] = []
    while pending:
        page = pending.popleft()
        if page in seen_pages:
            continue
        if len(seen_pages) >= MAX_PAGES:
            raise ProfileSourceError("Valopers page limit exceeded")
        seen_pages.add(page)
        found, page_links = parse_list_page(query(client, page, height).text, realm)
        for operator in found:
            if operator not in operators:
                operators.append(operator)
                if len(operators) > MAX_PROFILES:
                    raise ProfileSourceError("Valopers profile limit exceeded")
        for page_link in page_links:
            if page_link == page:
                continue
            if page_link in seen_pages:
                continue
            pending.append(page_link)
    profiles = [parse_detail(query(client, operator, height).text, operator, height, realm) for operator in operators]
    return SyncResult(height, tuple(sorted(profiles, key=lambda profile: profile.operator_address)))


def match_profiles(profiles: Iterable[ValidatorProfile], validators: Iterable[tuple[str, str, str]]) -> tuple[ValidatorProfile, ...]:
    normalized = []
    for profile in profiles:
        try:
            key_type, key_value = normalize_gpub(profile.consensus_pubkey)
            normalized.append(replace(profile, normalized_public_key_type=key_type,
                                      normalized_public_key_value=key_value, match_status="unmatched"))
        except ValueError:
            normalized.append(replace(profile, normalized_public_key_type=None,
                                      normalized_public_key_value=None, signing_address=None,
                                      match_status="invalid_pubkey"))
    counts = Counter((profile.normalized_public_key_type, profile.normalized_public_key_value)
                     for profile in normalized if profile.normalized_public_key_type)
    lookup: dict[tuple[str, str], list[str]] = {}
    for signing, key_type, key_value in validators:
        lookup.setdefault((key_type, key_value), []).append(signing)
    output = []
    for profile in normalized:
        key = (profile.normalized_public_key_type, profile.normalized_public_key_value)
        matches = lookup.get(key, [])
        if profile.normalized_public_key_type and (counts[key] > 1 or len(matches) > 1):
            profile = replace(profile, signing_address=None, match_status="ambiguous")
        elif profile.normalized_public_key_type and len(matches) == 1:
            if matches[0] != profile.source_signing_address:
                raise ProfileSourceError("source Signing Address conflicts with consensus public-key identity")
            profile = replace(profile, signing_address=matches[0], match_status="matched")
        output.append(profile)
    return tuple(sorted(output, key=lambda profile: profile.operator_address))
