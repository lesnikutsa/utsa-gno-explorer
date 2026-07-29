"""Bounded parsing for Gno auth and bank ABCI responses."""

import json
import re

from api.network_profile import NetworkProfile

MAX_JSON_BYTES = 262144
MAX_DEPTH = 12
MAX_BALANCES = 64
MAX_DENOM = 128
MAX_AMOUNT = 256
MAX_ACCOUNT_NUMBER = 40
MAX_PUBLIC_KEY_TYPE = 128
MAX_PUBLIC_KEY_VALUE = 4096


class AccountParseError(ValueError):
    """RPC account data failed bounded validation."""


def _depth(value, level: int = 0) -> None:
    if level > MAX_DEPTH:
        raise AccountParseError("nested data limit")
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)


def _json(text: str):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise AccountParseError("JSON size limit")
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise AccountParseError("malformed JSON") from exc
    _depth(value)
    return value


def _decimal(value, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        raise AccountParseError("malformed decimal")
    return value


def parse_auth_account(text: str, address: str) -> dict | None:
    value = _json(text)
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("BaseAccount"), dict):
        raise AccountParseError("malformed BaseAccount")
    base = value["BaseAccount"]
    if base.get("address") != address:
        raise AccountParseError("account address mismatch")
    account_number = _decimal(base.get("account_number"), MAX_ACCOUNT_NUMBER)
    sequence = _decimal(base.get("sequence"), MAX_ACCOUNT_NUMBER)
    public_key = base.get("public_key")
    if public_key is not None:
        if not isinstance(public_key, dict) or set(public_key) != {"@type", "value"}:
            raise AccountParseError("malformed public key")
        key_type, key_value = public_key["@type"], public_key["value"]
        if (not isinstance(key_type, str) or not 1 <= len(key_type) <= MAX_PUBLIC_KEY_TYPE
                or not isinstance(key_value, str) or not 1 <= len(key_value) <= MAX_PUBLIC_KEY_VALUE):
            raise AccountParseError("malformed public key")
        public_key = {"type": key_type, "value": key_value}
    return {"account_number": account_number, "sequence": sequence, "public_key": public_key}


def _display(amount: str, decimals: int) -> str:
    if decimals == 0:
        return amount
    padded = amount.zfill(decimals + 1)
    whole, fraction = padded[:-decimals], padded[-decimals:].rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def parse_coins(text: str, profile: NetworkProfile) -> list[dict]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise AccountParseError("coins size limit")
    if text == "":
        return []
    parts = text.split(",")
    if len(parts) > MAX_BALANCES:
        raise AccountParseError("balance count limit")
    balances, denoms = [], set()
    for part in parts:
        match = re.fullmatch(r"([0-9]+)([a-zA-Z][a-zA-Z0-9/:._-]*)", part)
        if match is None:
            raise AccountParseError("malformed coin")
        amount = _decimal(match.group(1), MAX_AMOUNT)
        denom = match.group(2)
        if len(denom) > MAX_DENOM or denom in denoms:
            raise AccountParseError("invalid denom")
        denoms.add(denom)
        native = denom == profile.native_denom
        decimals = profile.native_decimals if native else 0
        balances.append({"denom": denom, "amount": amount, "display_amount": _display(amount, decimals),
                         "symbol": profile.native_symbol if native else denom, "decimals": decimals})
    return sorted(balances, key=lambda item: item["denom"])
