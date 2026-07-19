"""Bounded, one-shot synchronization of public Valopers validator profiles."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from scripts.inspect_rpc import RpcError, result, to_int

DEFAULT_REALM = "gno.land/r/gnops/valopers"
MAX_PAGES = 20
MAX_PROFILES = 500
MAX_RESPONSE_BYTES = 1024 * 1024
ED25519_PREFIX = bytes.fromhex("1624de64")
SECP256K1_PREFIX = bytes.fromhex("eb5ae987")


class ProfileSourceError(RuntimeError):
    """Raised when the public source cannot be consumed completely and safely."""


@dataclass(frozen=True)
class SourceResponse:
    text: str
    height: int


@dataclass(frozen=True)
class ValidatorProfile:
    operator_address: str
    moniker: str
    description: str
    server_type: str | None
    keep_running: bool | None
    consensus_pubkey: str
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
    chk = 1
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                chk ^= generator
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def _convert_bits(values: Iterable[int], from_bits: int, to_bits: int, pad: bool) -> bytes:
    accumulator = 0
    bits = 0
    output = bytearray()
    maximum = (1 << to_bits) - 1
    for value in values:
        if value < 0 or value >> from_bits:
            raise ValueError("invalid bech32 data value")
        accumulator = (accumulator << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            output.append((accumulator >> bits) & maximum)
    if pad and bits:
        output.append((accumulator << (to_bits - bits)) & maximum)
    elif bits >= from_bits or ((accumulator << (to_bits - bits)) & maximum):
        raise ValueError("invalid bech32 padding")
    return bytes(output)


def normalize_gpub(value: str) -> tuple[str, str]:
    """Decode a checksummed Amino-prefixed gpub into the exact RPC key tuple."""
    if not isinstance(value, str) or not value or value.lower() != value or value.upper() == value:
        raise ValueError("gpub must use lowercase bech32")
    separator = value.rfind("1")
    if separator < 1 or separator + 7 > len(value) or value[:separator] != "gpub":
        raise ValueError("invalid gpub HRP or length")
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    try:
        words = [charset.index(char) for char in value[separator + 1 :]]
    except ValueError as exc:
        raise ValueError("invalid bech32 character") from exc
    if _bech32_polymod(_hrp_expand("gpub") + words) != 1:
        raise ValueError("invalid bech32 checksum")
    decoded = _convert_bits(words[:-6], 5, 8, False)
    types = {
        ED25519_PREFIX: ("/tm.PubKeyEd25519", 32),
        SECP256K1_PREFIX: ("/tm.PubKeySecp256k1", 33),
    }
    match = types.get(decoded[:4])
    if match is None:
        raise ValueError("unsupported Amino public key prefix")
    key_type, length = match
    raw = decoded[4:]
    if len(raw) != length:
        raise ValueError("invalid public key length")
    return key_type, base64.b64encode(raw).decode("ascii")


_PROFILE_LINK = re.compile(r"\[[^\]]+\]\((/r/gnops/valopers:([a-z0-9]+))\)")
_NEXT_LINK = re.compile(r"\[[^\]]*(?:next|›|→)[^\]]*\]\((/r/gnops/valopers\?[^)]+)\)", re.I)


def parse_list_page(text: str, realm: str = DEFAULT_REALM) -> tuple[list[str], str | None]:
    _bounded(text)
    expected = "/r/" + realm.split("/r/", 1)[-1]
    operators: list[str] = []
    for path, address in _PROFILE_LINK.findall(text):
        if not path.startswith(expected + ":"):
            raise ProfileSourceError("profile link escaped the configured realm")
        if address not in operators:
            operators.append(address)
    if not operators:
        raise ProfileSourceError("Valopers list page contains no profile links")
    next_paths = _NEXT_LINK.findall(text)
    if len(set(next_paths)) > 1:
        raise ProfileSourceError("Valopers list page has conflicting next links")
    next_path = next_paths[0] if next_paths else None
    if next_path and not next_path.startswith(expected + "?"):
        raise ProfileSourceError("pagination link escaped the configured realm")
    return operators, next_path


def _field(text: str, *names: str) -> str | None:
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(rf"(?im)^[ \t]*(?:[-*][ \t]*)?(?:\*\*)?(?:{alternatives})(?:\*\*)?[ \t]*:[ \t]*(.*?)[ \t]*$", text)
    if not match:
        return None
    return re.sub(r"\\([\\`*_{}\[\]()#+.!-])", r"\1", match.group(1)).strip()


def parse_detail(text: str, operator: str, height: int, realm: str = DEFAULT_REALM) -> ValidatorProfile:
    _bounded(text)
    source_operator = _field(text, "Operator Address", "Address")
    if source_operator and source_operator != operator:
        raise ProfileSourceError("detail operator address does not match its profile link")
    moniker = _field(text, "Moniker")
    pubkey = _field(text, "Consensus Public Key", "Public Key", "PubKey")
    if not operator or not moniker or not pubkey:
        raise ProfileSourceError("profile is missing operator address, moniker, or consensus public key")
    description = _field(text, "Description") or ""
    server_type = _field(text, "Server Type", "ServerType")
    keep_raw = _field(text, "Keep Running", "KeepRunning")
    if keep_raw is None:
        keep_running = None
    elif keep_raw.lower() in {"true", "yes"}:
        keep_running = True
    elif keep_raw.lower() in {"false", "no"}:
        keep_running = False
    else:
        raise ProfileSourceError("profile keepRunning value is not boolean")
    canonical = json.dumps([operator, moniker, description, server_type, keep_running, pubkey], ensure_ascii=False, separators=(",", ":"))
    return ValidatorProfile(operator, moniker, description, server_type, keep_running, pubkey, realm,
                            f"/r/{realm.split('/r/', 1)[-1]}:{operator}", height,
                            hashlib.sha256(canonical.encode()).hexdigest())


def _bounded(text: str) -> None:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ProfileSourceError("Valopers response is malformed or exceeds the size limit")


def decode_vm_response(payload: dict, expected_height: int) -> SourceResponse:
    response = result(payload).get("response")
    if not isinstance(response, dict):
        raise ProfileSourceError("malformed ABCI query response")
    height = to_int(response.get("height"))
    if height != expected_height:
        raise ProfileSourceError(f"VM query height mismatch: expected {expected_height}, received {height}")
    encoded = response.get("value")
    try:
        raw = base64.b64decode(encoded, validate=True)
        text = raw.decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ProfileSourceError("malformed VM query value") from exc
    _bounded(text)
    return SourceResponse(text, height)


def query_render(client, render_path: str, height: int) -> SourceResponse:
    return decode_vm_response(client.get("abci_query", path="vm/qrender", data=render_path, height=height, prove="false"), height)


def collect_profiles(client, height: int, realm: str = DEFAULT_REALM,
                     query: Callable[[object, str, int], SourceResponse] = query_render) -> SyncResult:
    page = realm
    seen_pages: set[str] = set()
    operators: list[str] = []
    for _ in range(MAX_PAGES):
        if page in seen_pages:
            raise ProfileSourceError("Valopers pagination loop detected")
        seen_pages.add(page)
        response = query(client, page, height)
        found, next_path = parse_list_page(response.text, realm)
        for operator in found:
            if operator not in operators:
                operators.append(operator)
                if len(operators) > MAX_PROFILES:
                    raise ProfileSourceError("Valopers profile limit exceeded")
        if not next_path:
            break
        page = realm + "?" + next_path.split("?", 1)[1]
    else:
        raise ProfileSourceError("Valopers page limit exceeded")
    profiles = [parse_detail(query(client, f"{realm}:{operator}", height).text, operator, height, realm) for operator in operators]
    return SyncResult(height, tuple(sorted(profiles, key=lambda item: item.operator_address)))


def match_profiles(profiles: Iterable[ValidatorProfile], validators: Iterable[tuple[str, str, str]]) -> tuple[ValidatorProfile, ...]:
    normalized: list[ValidatorProfile] = []
    for profile in profiles:
        try:
            key_type, key_value = normalize_gpub(profile.consensus_pubkey)
            normalized.append(replace(profile, normalized_public_key_type=key_type,
                                      normalized_public_key_value=key_value, match_status="unmatched"))
        except ValueError:
            normalized.append(replace(profile, normalized_public_key_type=None,
                                      normalized_public_key_value=None, signing_address=None,
                                      match_status="invalid_pubkey"))
    counts = Counter((p.normalized_public_key_type, p.normalized_public_key_value) for p in normalized if p.normalized_public_key_type)
    lookup: dict[tuple[str, str], list[str]] = {}
    for signing, key_type, key_value in validators:
        lookup.setdefault((key_type, key_value), []).append(signing)
    output = []
    for profile in normalized:
        key = (profile.normalized_public_key_type, profile.normalized_public_key_value)
        if profile.normalized_public_key_type and counts[key] > 1:
            profile = replace(profile, signing_address=None, match_status="ambiguous")
        elif profile.normalized_public_key_type and len(lookup.get(key, [])) == 1:
            profile = replace(profile, signing_address=lookup[key][0], match_status="matched")
        elif profile.normalized_public_key_type and len(lookup.get(key, [])) > 1:
            profile = replace(profile, signing_address=None, match_status="ambiguous")
        output.append(profile)
    return tuple(sorted(output, key=lambda item: item.operator_address))
