"""Bounded live Cosmos account snapshot for the multi-network explorer."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse


MAX_ACCOUNT_ROWS = 200
MAX_UNBONDING_ENTRIES = 400


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CosmosAccountCoin(StrictModel):
    denom: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")


class CosmosAccountPublicKey(StrictModel):
    type: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=512)


class CosmosAccountValidatorRef(StrictModel):
    operator_address: str = Field(min_length=3, max_length=90)
    moniker: str | None = Field(default=None, max_length=256)
    category: Literal["active", "inactive", "jailed"] | None = None
    avatar_url: str | None = Field(default=None, max_length=2048, pattern=r"^https://")


class CosmosAccountDelegation(StrictModel):
    validator: CosmosAccountValidatorRef
    shares: str = Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
    balance: CosmosAccountCoin
    rewards: list[CosmosAccountCoin] = Field(default_factory=list, max_length=32)


class CosmosAccountReward(StrictModel):
    validator: CosmosAccountValidatorRef
    rewards: list[CosmosAccountCoin] = Field(max_length=32)


class CosmosAccountUnbondingEntry(StrictModel):
    creation_height: int = Field(ge=0)
    completion_time: str = Field(min_length=20, max_length=64)
    initial_balance: str = Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)$")
    balance: str = Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)$")
    remaining_seconds: int = Field(ge=0)


class CosmosAccountUnbonding(StrictModel):
    validator: CosmosAccountValidatorRef
    denom: str | None = Field(default=None, min_length=1, max_length=128)
    entries: list[CosmosAccountUnbondingEntry] = Field(max_length=MAX_UNBONDING_ENTRIES)


class CosmosAccountSectionStates(StrictModel):
    auth: Literal["available", "unavailable"]
    bank: Literal["available", "unavailable"]
    staking: Literal["available", "unavailable"]
    unbonding: Literal["available", "unavailable"]
    rewards: Literal["available", "unavailable"]
    withdraw_address: Literal["available", "unavailable"]


class CosmosAccountDetailResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    address: str = Field(min_length=3, max_length=90)
    exists: bool
    account_type: str | None = Field(default=None, max_length=256)
    account_number: int | None = Field(default=None, ge=0)
    sequence: int | None = Field(default=None, ge=0)
    public_key: CosmosAccountPublicKey | None = None
    bond_denom: str | None = Field(default=None, min_length=1, max_length=128)
    balances: list[CosmosAccountCoin] = Field(max_length=MAX_ACCOUNT_ROWS)
    balances_truncated: bool
    delegated_total: list[CosmosAccountCoin] = Field(max_length=32)
    rewards_total: list[CosmosAccountCoin] = Field(max_length=32)
    rewards_by_validator: list[CosmosAccountReward] = Field(max_length=MAX_ACCOUNT_ROWS)
    delegations: list[CosmosAccountDelegation] = Field(max_length=MAX_ACCOUNT_ROWS)
    delegations_truncated: bool
    unbonding: list[CosmosAccountUnbonding] = Field(max_length=MAX_ACCOUNT_ROWS)
    unbonding_truncated: bool
    withdraw_address: str | None = Field(default=None, max_length=90)
    validator_relation: CosmosAccountValidatorRef | None = None
    states: CosmosAccountSectionStates


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict) or len(value) > 256:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _text(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip() or not value.isprintable():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse(f"invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 20):
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if result < 0 or result > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def _amount(value: object, name: str, *, integer_only: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise MalformedUpstreamResponse(f"invalid {name}")
    if integer_only and (not value.isascii() or not value.isdigit()):
        raise MalformedUpstreamResponse(f"invalid {name}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise MalformedUpstreamResponse(f"invalid {name}") from None
    if not number.is_finite() or number < 0:
        raise MalformedUpstreamResponse(f"invalid {name}")
    if integer_only and number != number.to_integral_value():
        raise MalformedUpstreamResponse(f"invalid {name}")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _coin(value: object, *, integer_only: bool = False) -> dict[str, str]:
    coin = _mapping(value, "coin")
    return {
        "denom": _text(coin.get("denom"), "coin denom", 128),
        "amount": _amount(coin.get("amount"), "coin amount", integer_only=integer_only),
    }


def _coins(value: object, *, integer_only: bool = False, maximum: int = MAX_ACCOUNT_ROWS) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > maximum:
        raise MalformedUpstreamResponse("invalid coin list")
    rows = [_coin(item, integer_only=integer_only) for item in value]
    seen = set()
    result = []
    for row in rows:
        if row["denom"] in seen:
            raise MalformedUpstreamResponse("duplicate coin denom")
        seen.add(row["denom"])
        result.append(row)
    return result


def _sum_coins(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        try:
            totals[row["denom"]] = totals.get(row["denom"], Decimal(0)) + Decimal(row["amount"])
        except (InvalidOperation, KeyError):
            raise MalformedUpstreamResponse("invalid coin total") from None
    result = []
    for denom in sorted(totals):
        text = format(totals[denom], "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        result.append({"denom": denom, "amount": text or "0"})
    return result


def _find_base_account(value: object, expected_address: str, depth: int = 0) -> dict | None:
    if depth > 6 or not isinstance(value, dict) or len(value) > 256:
        return None
    if value.get("address") == expected_address and ("account_number" in value or "sequence" in value):
        return value
    for nested in value.values():
        if isinstance(nested, dict):
            found = _find_base_account(nested, expected_address, depth + 1)
            if found is not None:
                return found
    return None


def _account_identity(payload: object, expected_address: str) -> dict:
    account = _mapping(_mapping(payload, "auth response").get("account"), "account")
    base = _find_base_account(account, expected_address)
    if base is None:
        raise MalformedUpstreamResponse("account identity mismatch")
    account_type = account.get("@type")
    if account_type is not None:
        account_type = _text(account_type, "account type", 256)
    account_number = _integer(base.get("account_number"), "account number") if base.get("account_number") is not None else None
    sequence = _integer(base.get("sequence"), "sequence") if base.get("sequence") is not None else None
    public_key = None
    raw_key = base.get("pub_key")
    if isinstance(raw_key, dict):
        key_type = raw_key.get("@type") or raw_key.get("type")
        key_value = raw_key.get("key") or raw_key.get("value")
        if key_type and key_value:
            key_type = _text(key_type, "public key type", 256)
            key_value = _text(key_value, "public key", 512)
            try:
                base64.b64decode(key_value, validate=True)
            except (ValueError, TypeError):
                raise MalformedUpstreamResponse("invalid public key") from None
            public_key = {"type": key_type, "value": key_value}
    return {"account_type": account_type, "account_number": account_number,
            "sequence": sequence, "public_key": public_key}


def _bank_balances(payload: object) -> tuple[list[dict], bool]:
    payload = _mapping(payload, "bank response")
    balances = _coins(payload.get("balances"), integer_only=True)
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    return balances, bool(pagination.get("next_key"))


def _validator_refs(service, raw_validators: object) -> dict[str, dict]:
    from .validators import category

    if not isinstance(raw_validators, list):
        return {}
    result = {}
    for raw in raw_validators:
        if not isinstance(raw, dict):
            continue
        operator = raw.get("operator_address")
        if not isinstance(operator, str) or not operator.startswith(service.definition.validator_operator_prefix + "1"):
            continue
        description = raw.get("description") if isinstance(raw.get("description"), dict) else {}
        moniker = description.get("moniker")
        identity = description.get("identity")
        if not isinstance(moniker, str) or not moniker.strip():
            moniker = operator
        avatar = service._avatar(identity) if isinstance(identity, str) and identity.isascii() and identity.isalnum() else None
        result[operator] = {
            "operator_address": operator,
            "moniker": moniker[:256],
            "category": category(raw),
            "avatar_url": avatar,
        }
    return result


def _validator_ref(operator_address: str, refs: dict[str, dict]) -> dict:
    return refs.get(operator_address) or {"operator_address": operator_address,
                                          "moniker": None, "category": None, "avatar_url": None}


def _delegations(payload: object, expected_address: str) -> tuple[list[dict], bool]:
    payload = _mapping(payload, "delegations response")
    rows = payload.get("delegation_responses")
    if not isinstance(rows, list) or len(rows) > MAX_ACCOUNT_ROWS:
        raise MalformedUpstreamResponse("invalid account delegations")
    items = []
    for raw in rows:
        raw = _mapping(raw, "delegation response")
        delegation = _mapping(raw.get("delegation"), "delegation")
        if _text(delegation.get("delegator_address"), "delegator address", 90) != expected_address:
            raise MalformedUpstreamResponse("delegator address mismatch")
        operator = _text(delegation.get("validator_address"), "validator address", 90)
        items.append({"operator_address": operator,
                      "shares": _amount(delegation.get("shares"), "delegation shares"),
                      "balance": _coin(raw.get("balance"), integer_only=True)})
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    return items, bool(pagination.get("next_key"))


def _parse_completion_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    fraction_pos = normalized.find(".")
    if fraction_pos != -1:
        timezone_pos = max(normalized.rfind("+"), normalized.rfind("-"))
        if timezone_pos > fraction_pos:
            fractional_digits = timezone_pos - fraction_pos - 1
            if fractional_digits > 6:
                normalized = normalized[:fraction_pos + 7] + normalized[timezone_pos:]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise MalformedUpstreamResponse("invalid completion time") from None
    if parsed.tzinfo is None:
        raise MalformedUpstreamResponse("invalid completion timezone")
    return parsed


def _unbonding(payload: object, expected_address: str, now: datetime) -> tuple[list[dict], bool]:
    payload = _mapping(payload, "unbonding response")
    rows = payload.get("unbonding_responses")
    if not isinstance(rows, list) or len(rows) > MAX_ACCOUNT_ROWS:
        raise MalformedUpstreamResponse("invalid account unbonding")
    groups = []
    total_entries = 0
    for raw in rows:
        raw = _mapping(raw, "unbonding delegation")
        if _text(raw.get("delegator_address"), "delegator address", 90) != expected_address:
            raise MalformedUpstreamResponse("unbonding delegator mismatch")
        operator = _text(raw.get("validator_address"), "validator address", 90)
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raise MalformedUpstreamResponse("invalid unbonding entries")
        normalized_entries = []
        for entry in entries:
            total_entries += 1
            if total_entries > MAX_UNBONDING_ENTRIES:
                raise MalformedUpstreamResponse("too many unbonding entries")
            entry = _mapping(entry, "unbonding entry")
            completion = _text(entry.get("completion_time"), "completion time", 64)
            parsed = _parse_completion_time(completion)
            remaining = max(0, int((parsed.astimezone(timezone.utc) - now).total_seconds()))
            normalized_entries.append({
                "creation_height": _integer(entry.get("creation_height"), "creation height"),
                "completion_time": completion,
                "initial_balance": _amount(entry.get("initial_balance"), "initial balance", integer_only=True),
                "balance": _amount(entry.get("balance"), "unbonding balance", integer_only=True),
                "remaining_seconds": remaining,
            })
        groups.append({"operator_address": operator, "entries": normalized_entries})
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    return groups, bool(pagination.get("next_key"))


def _reward_map(payload: object) -> tuple[dict[str, list[dict]], list[dict]]:
    payload = _mapping(payload, "rewards response")
    rows = payload.get("rewards")
    if not isinstance(rows, list) or len(rows) > MAX_ACCOUNT_ROWS:
        raise MalformedUpstreamResponse("invalid delegation rewards")
    result: dict[str, list[dict]] = {}
    for raw in rows:
        raw = _mapping(raw, "delegation reward")
        operator = _text(raw.get("validator_address"), "reward validator", 90)
        if operator in result:
            raise MalformedUpstreamResponse("duplicate reward validator")
        result[operator] = _coins(raw.get("reward"), maximum=32)
    return result, _coins(payload.get("total"), maximum=32)


def _bond_denom(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    try:
        return _text(params.get("bond_denom"), "bond denom", 128)
    except MalformedUpstreamResponse:
        return None


async def load_account_snapshot(service, address: str) -> dict:
    """Aggregate current x/auth, x/bank, x/staking and x/distribution state.

    The function intentionally contains no transaction-history lookup and no database/indexer dependency.
    Individual optional Cosmos sections degrade independently so one unsupported module does not hide balances.
    """
    from .service import reencode_bech32_address, valid_bech32_address

    if not valid_bech32_address(address, service.definition.account_prefix):
        raise ValueError("invalid account address")

    encoded = quote(address, safe="")
    page = f"pagination.limit={MAX_ACCOUNT_ROWS}&pagination.count_total=false"
    requests = {
        "auth": service._rest("account_auth", f"/cosmos/auth/v1beta1/accounts/{encoded}"),
        "bank": service._rest("account_balances", f"/cosmos/bank/v1beta1/balances/{encoded}?{page}"),
        "staking": service._rest("account_delegations", f"/cosmos/staking/v1beta1/delegations/{encoded}?{page}"),
        "unbonding": service._rest("account_unbonding", f"/cosmos/staking/v1beta1/delegators/{encoded}/unbonding_delegations?{page}"),
        "rewards": service._rest("account_rewards", f"/cosmos/distribution/v1beta1/delegators/{encoded}/rewards"),
        "withdraw_address": service._rest("account_withdraw_address", f"/cosmos/distribution/v1beta1/delegators/{encoded}/withdraw_address"),
        "staking_params": service._rest("account_staking_params", "/cosmos/staking/v1beta1/params"),
    }
    names = tuple(requests)
    raw = await asyncio.gather(*(requests[name] for name in names), return_exceptions=True)
    outcomes = dict(zip(names, raw))
    section_names = ("auth", "bank", "staking", "unbonding", "rewards", "withdraw_address")
    states = {name: "unavailable" if isinstance(outcomes[name], BaseException) else "available"
              for name in section_names}
    if all(state == "unavailable" for state in states.values()):
        raise AllEndpointsUnavailable("account snapshot unavailable")

    identity = {"account_type": None, "account_number": None, "sequence": None, "public_key": None}
    if states["auth"] == "available":
        try:
            identity = _account_identity(outcomes["auth"], address)
        except MalformedUpstreamResponse:
            states["auth"] = "unavailable"

    balances, balances_truncated = [], False
    if states["bank"] == "available":
        try:
            balances, balances_truncated = _bank_balances(outcomes["bank"])
        except MalformedUpstreamResponse:
            states["bank"] = "unavailable"

    delegation_rows, delegations_truncated = [], False
    if states["staking"] == "available":
        try:
            delegation_rows, delegations_truncated = _delegations(outcomes["staking"], address)
        except MalformedUpstreamResponse:
            states["staking"] = "unavailable"

    now = service._wall_clock().astimezone(timezone.utc)
    unbonding_rows, unbonding_truncated = [], False
    if states["unbonding"] == "available":
        try:
            unbonding_rows, unbonding_truncated = _unbonding(outcomes["unbonding"], address, now)
        except MalformedUpstreamResponse:
            states["unbonding"] = "unavailable"

    rewards_by_operator, rewards_total = {}, []
    if states["rewards"] == "available":
        try:
            rewards_by_operator, rewards_total = _reward_map(outcomes["rewards"])
        except MalformedUpstreamResponse:
            states["rewards"] = "unavailable"

    withdraw_address = None
    if states["withdraw_address"] == "available":
        try:
            withdraw_address = _text(_mapping(outcomes["withdraw_address"], "withdraw address response").get("withdraw_address"),
                                     "withdraw address", 90)
            if not valid_bech32_address(withdraw_address, service.definition.account_prefix):
                raise MalformedUpstreamResponse("invalid withdraw address")
        except MalformedUpstreamResponse:
            states["withdraw_address"] = "unavailable"
            withdraw_address = None

    bond_denom = None if isinstance(outcomes["staking_params"], BaseException) else _bond_denom(outcomes["staking_params"])
    if bond_denom is None and delegation_rows:
        bond_denom = delegation_rows[0]["balance"]["denom"]

    refs = {}
    validator_relation = None
    try:
        raw_validators = await service.cache.get_or_load(
            (service.definition.transport.network_id, "validator_set"), 15.0, service._all_validators)
        refs = _validator_refs(service, raw_validators)
        relation_operator = reencode_bech32_address(
            address, service.definition.account_prefix, service.definition.validator_operator_prefix)
        validator_relation = refs.get(relation_operator)
    except Exception:
        refs = {}

    delegations = [{"validator": _validator_ref(row["operator_address"], refs),
                    "shares": row["shares"], "balance": row["balance"],
                    "rewards": rewards_by_operator.get(row["operator_address"], [])}
                   for row in delegation_rows]
    rewards_by_validator = [
        {"validator": _validator_ref(operator, refs), "rewards": rewards}
        for operator, rewards in sorted(rewards_by_operator.items())
    ]
    unbonding = [{"validator": _validator_ref(row["operator_address"], refs),
                  "denom": bond_denom, "entries": row["entries"]}
                 for row in unbonding_rows]
    delegated_total = _sum_coins([row["balance"] for row in delegation_rows])

    exists = bool(identity["account_number"] is not None or balances or delegation_rows or unbonding_rows or rewards_total)
    if all(state == "unavailable" for state in states.values()):
        raise AllEndpointsUnavailable("account snapshot malformed")
    payload = {
        "network_id": service.definition.transport.network_id,
        "address": address,
        "exists": exists,
        **identity,
        "bond_denom": bond_denom,
        "balances": balances,
        "balances_truncated": balances_truncated,
        "delegated_total": delegated_total,
        "rewards_total": rewards_total,
        "rewards_by_validator": rewards_by_validator,
        "delegations": delegations,
        "delegations_truncated": delegations_truncated,
        "unbonding": unbonding,
        "unbonding_truncated": unbonding_truncated,
        "withdraw_address": withdraw_address,
        "validator_relation": validator_relation,
        "states": states,
    }
    return CosmosAccountDetailResponse.model_validate(payload, strict=True).model_dump()
