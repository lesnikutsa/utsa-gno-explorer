"""Request-driven, strictly normalized Cosmos overview aggregation."""

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import hashlib
import math
import re
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from .adapter import CosmosAdapter
from .cache import RequestCache
from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse, RejectedEndpoint
from .parsing import parse_node_status, parse_rest_node_info, parse_rpc_block
from .registry import NetworkDefinition
from .schemas import (AssetsSupply, Distribution, Governance, MarketResponse,
                      MissedValidator, Mint, OverviewResponse, Slashing, Staking)
from .blocks import estimate_eta_result, metadata, metadata_sample
from .rfc3339 import parse_rfc3339
from .errors import HistoryUnavailable

SECTION_TTL = 5.0
MARKET_TTL = 30.0
MAX_PAGES = 10
PAGE_SIZE = 200
MAX_LIST_ITEMS = MAX_PAGES * PAGE_SIZE
_UNSIGNED_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_SIGNED_DECIMAL = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")


def _mapping(value: object, name: str = "object") -> dict:
    if not isinstance(value, dict) or len(value) > 256:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _field(payload: object, *names: str) -> object:
    """Find a unique bounded scalar/list parameter through known wrapper objects."""
    wanted = set(names)
    queue = [(payload, 0)]
    found = []
    while queue:
        item, depth = queue.pop(0)
        if not isinstance(item, dict) or len(item) > 256 or depth > 4:
            continue
        for key, value in item.items():
            if key in wanted:
                found.append(value)
            elif isinstance(value, dict):
                queue.append((value, depth + 1))
    if not found:
        raise MalformedUpstreamResponse(f"missing {names[0]}")
    return found[0]


def _decimal(value: object, name: str, *, nonnegative: bool = True) -> str:
    pattern = _UNSIGNED_DECIMAL if nonnegative else _SIGNED_DECIMAL
    if (isinstance(value, bool) or not isinstance(value, str) or not value
            or len(value) > 128 or pattern.fullmatch(value) is None):
        raise MalformedUpstreamResponse(f"invalid {name}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise MalformedUpstreamResponse(f"invalid {name}") from None
    if not number.is_finite() or (nonnegative and number < 0):
        raise MalformedUpstreamResponse(f"invalid {name}")
    return format(number, "f")


def _integer(value: object, name: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse(f"invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 20):
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if (nonnegative and result < 0) or abs(result) > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _text(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip() or not value.isprintable():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _coin(payload: object, expected_denom: str) -> str:
    coin = _mapping(payload, "coin")
    if coin.get("denom") != expected_denom:
        raise MalformedUpstreamResponse("wrong coin denom")
    return _decimal(coin.get("amount"), "coin amount")


def _coin_object(payload: object, expected_denom: str | None = None) -> dict[str, str]:
    coin = _mapping(payload, "coin")
    denom = _text(coin.get("denom"), "coin denom", 128)
    if expected_denom is not None and denom != expected_denom:
        raise MalformedUpstreamResponse("wrong coin denom")
    return {"denom": denom, "amount": _decimal(coin.get("amount"), "coin amount")}


def _coins(payload: object, allowed: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(payload, list) or len(payload) > MAX_LIST_ITEMS:
        raise MalformedUpstreamResponse("invalid coin list")
    result = {denom: "0" for denom in allowed}
    for item in payload:
        coin = _mapping(item, "coin")
        if coin.get("denom") in result:
            result[coin["denom"]] = _decimal(coin.get("amount"), "coin amount")
    return result


def _bech32_polymod(values):
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for index, generator in enumerate((0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)):
            if top >> index & 1:
                chk ^= generator
    return chk


def _convert_bits(data: bytes):
    acc = bits = 0
    result = []
    for value in data:
        acc = (acc << 8) | value
        bits += 8
        while bits >= 5:
            bits -= 5
            result.append((acc >> bits) & 31)
    if bits:
        result.append((acc << (5 - bits)) & 31)
    return result


def consensus_address(public_key: object, prefix: str) -> str:
    key = _mapping(public_key, "consensus public key")
    encoded = key.get("key")
    if not isinstance(encoded, str) or len(encoded) > 128:
        raise MalformedUpstreamResponse("invalid consensus public key")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise MalformedUpstreamResponse("invalid consensus public key") from None
    if len(raw) != 32:
        raise MalformedUpstreamResponse("invalid consensus public key")
    words = _convert_bits(hashlib.sha256(raw).digest()[:20])
    expanded = [ord(char) >> 5 for char in prefix] + [0] + [ord(char) & 31 for char in prefix]
    polymod = _bech32_polymod(expanded + words + [0] * 6) ^ 1
    checksum = [(polymod >> 5 * (5 - index)) & 31 for index in range(6)]
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    return prefix + "1" + "".join(charset[item] for item in words + checksum)


class CosmosService:
    def __init__(self, definition: NetworkDefinition, *, client: httpx.AsyncClient,
                 cache: RequestCache, wall_clock=None):
        self.definition = definition
        self.cache = cache
        self.adapter = CosmosAdapter(definition.transport, client=client, cache=cache)
        self.transport = self.adapter._transport
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _public_block(block):
        return {"height": block.height, "hash": block.block_hash,
                "timestamp": block.block_time, "proposer": block.proposer_address,
                "transaction_count": block.transaction_count}

    async def blocks(self, limit: int = 10):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        head = await self.adapter.node_status()
        low = max(1, head.local_height - limit + 1)
        items = await self.cache.get_or_load(
            (self.definition.transport.network_id, "blocks", (low, head.local_height)), 2.0,
            lambda: metadata(self.adapter, low, head.local_height))
        return {"source": "rpc_metadata", "blocks": sorted(items, key=lambda item: item["height"], reverse=True)[:limit]}

    async def _status_observations(self):
        async def load():
            observations = []
            for endpoint in self.definition.transport.rpc_endpoints:
                try:
                    payload = await self.transport.get_object(endpoint, "/status")
                    status = parse_node_status(
                        payload, network_id=self.definition.transport.network_id,
                        expected_chain_id=self.definition.transport.chain_id,
                        source_host=self.adapter._host(endpoint))
                    observations.append((endpoint, status))
                except Exception:
                    continue
            if not observations:
                raise AllEndpointsUnavailable("no identity-validated RPC status")
            return observations
        key = (self.definition.transport.network_id, "block_status_observations", ())
        return await self.cache.get_or_load(key, 2.0, load)

    async def _observed_block(self, height, observations):
        pruning = []
        attempted = False
        for endpoint, status in sorted(observations, key=lambda item: item[1].local_height, reverse=True):
            if status.local_height < height:
                continue
            attempted = True
            try:
                payload = await self.transport.get_object(
                    endpoint, f"/block?height={height}", accept_error_payload=True)
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("data") or error.get("message") or "")
                    match = re.search(
                        r"height\s+\d+\s+is not available(?:, lowest height is\s+(\d+))?",
                        message, re.IGNORECASE)
                    if match:
                        pruning.append(int(match.group(1)) if match.group(1) else None)
                        continue
                    raise RejectedEndpoint("http_status")
                block = parse_rpc_block(
                    payload, network_id=self.definition.transport.network_id,
                    expected_chain_id=self.definition.transport.chain_id)
                if block.height != height:
                    raise RejectedEndpoint("wrong_height")
                return block
            except (MalformedUpstreamResponse, RejectedEndpoint):
                continue
        if pruning and attempted and len(pruning) == sum(
                status.local_height >= height for _endpoint, status in observations):
            known = [item for item in pruning if item is not None]
            raise HistoryUnavailable(height, min(known) if known else None)
        raise AllEndpointsUnavailable("observed block unavailable")

    async def block_lookup(self, height: int):
        observations = await self._status_observations()
        observed_height = max(status.local_height for _endpoint, status in observations)
        confirmed = [status for _endpoint, status in observations if not status.catching_up]
        confirmed_height = max((status.local_height for status in confirmed), default=None)
        if height > observed_height:
            if confirmed_height is None:
                return {"state": "node_not_synced", "local_height": observed_height,
                        "source": "rpc", "block": None, "eta": None,
                        "eta_unavailable_reason": None}
            try:
                key = (self.definition.transport.network_id, "eta_sample", (confirmed_height,))
                history = await self.cache.get_or_load(
                    key, 2.0, lambda: metadata_sample(self.adapter, confirmed_height))
                eta, reason = estimate_eta_result(history, height)
                if eta and history:
                    latest_time = parse_rfc3339(max(history, key=lambda item: item["height"])["timestamp"])
                    if self._wall_clock() - latest_time > timedelta(seconds=max(300, eta["average_block_seconds"] * 20)):
                        eta, reason = None, "network_stalled"
            except (HistoryUnavailable, AllEndpointsUnavailable):
                eta, reason = None, "insufficient_history"
            return {"state": "future", "local_height": observed_height, "source": "rpc",
                    "block": None, "eta": eta,
                    "eta_unavailable_reason": reason}
        try:
            key = (self.definition.transport.network_id, "observed_block", (height,))
            block = await self.cache.get_or_load(
                key, 2.0, lambda: self._observed_block(height, observations))
            return {"state": "available", "local_height": observed_height, "source": "rpc",
                    "block": self._public_block(block), "eta": None, "eta_unavailable_reason": None}
        except HistoryUnavailable:
            state = "history_unavailable"
        return {"state": state, "local_height": observed_height, "source": "rpc",
                "block": None, "eta": None, "eta_unavailable_reason": None}

    async def _rest(self, name: str, path: str, validator=None):
        key = (self.definition.transport.network_id, "overview_rest", (name, path))
        async def load():
            candidates = await self.adapter._cached_candidates("rest")
            for candidate in candidates:
                try:
                    payload = await self.transport.get_object(candidate.endpoint, path)
                    return validator(payload) if validator is not None else payload
                except Exception:
                    continue
            raise AllEndpointsUnavailable(f"{name} unavailable")
        return await self.cache.get_or_load(key, SECTION_TTL, load)

    async def _rest_many(self, requests):
        return await asyncio.gather(*(self._rest(name, path) for name, path in requests))

    async def _node_versions(self):
        payload = await self._rest("node_info", "/cosmos/base/tendermint/v1beta1/node_info")
        return parse_rest_node_info(payload, expected_chain_id=self.definition.transport.chain_id)

    async def _supply(self):
        async def one(asset):
            amount = await self._rest(
                f"supply_{asset.base}", f"/cosmos/bank/v1beta1/supply/by_denom?denom={asset.base}",
                lambda payload: _coin(payload.get("amount"), asset.base))
            return {"base": asset.base, "display": asset.display, "symbol": asset.symbol,
                    "exponent": asset.exponent, "total_supply": amount}
        return {"assets": list(await asyncio.gather(*(one(asset) for asset in self.definition.assets)))}

    async def _bonded_validators(self):
        return await self._paginate(
            "bonded_validators", "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED", "validators")

    async def _staking(self, supply: dict, validators: list):
        pool, params_payload = await self._rest_many((
            ("staking_pool", "/cosmos/staking/v1beta1/pool"),
            ("staking_params", "/cosmos/staking/v1beta1/params"),
        ))
        params = _mapping(params_payload.get("params"), "staking params")
        bonded = _decimal(_field(pool, "bonded_tokens"), "bonded tokens")
        not_bonded = _decimal(_field(pool, "not_bonded_tokens"), "not bonded tokens")
        bond_denom = _text(params.get("bond_denom"), "bond denom", 128)
        supplies = {item["base"]: item["total_supply"] for item in supply["assets"]}
        if bond_denom not in supplies:
            raise MalformedUpstreamResponse("bond denom supply unavailable")
        total = Decimal(supplies[bond_denom])
        ratio = "0" if total == 0 else format(Decimal(bonded) / total, "f")
        active_validator_count = sum(
            1 for validator in validators
            if _mapping(validator, "validator").get("status") == "BOND_STATUS_BONDED")
        return {"bonded_tokens": bonded, "not_bonded_tokens": not_bonded, "bonded_ratio": ratio,
                "active_validator_count": active_validator_count,
                "max_validators": _integer(params.get("max_validators"), "max validators"),
                "unbonding_time": _text(params.get("unbonding_time"), "unbonding time", 64),
                "max_entries": _integer(params.get("max_entries"), "max entries"),
                "historical_entries": _integer(params.get("historical_entries"), "historical entries"),
                "bond_denom": bond_denom,
                "min_commission_rate": (_decimal(params["min_commission_rate"], "minimum commission rate")
                                        if params.get("min_commission_rate") is not None else None),
                "max_commission_rate": (_decimal(params["max_commission_rate"], "maximum commission rate")
                                        if params.get("max_commission_rate") is not None else None),
                "key_rotation_fee": (_coin_object(params["key_rotation_fee"])
                                     if params.get("key_rotation_fee") is not None else None)}

    async def _mint(self):
        inflation, params = await self._rest_many((("mint_inflation", "/cosmos/mint/v1beta1/inflation"),
                                                    ("mint_params", "/cosmos/mint/v1beta1/params")))
        return {"current_inflation": _decimal(_field(inflation, "inflation"), "inflation"),
                "inflation_min": _decimal(_field(params, "inflation_min"), "minimum inflation"),
                "inflation_max": _decimal(_field(params, "inflation_max"), "maximum inflation"),
                "inflation_rate_change": _decimal(_field(params, "inflation_rate_change"), "inflation rate change"),
                "goal_bonded": _decimal(_field(params, "goal_bonded"), "goal bonded"),
                "blocks_per_year": _integer(_field(params, "blocks_per_year"), "blocks per year")}

    async def _slashing(self):
        params = await self._rest("slashing_params", "/cosmos/slashing/v1beta1/params")
        window = _integer(_field(params, "signed_blocks_window"), "signed blocks window")
        minimum = _decimal(_field(params, "min_signed_per_window"), "minimum signed per window")
        minimum_decimal = Decimal(minimum)
        precision = len(minimum_decimal.as_tuple().digits) + len(str(window)) + 2
        with localcontext() as context:
            context.prec = precision
            required = int((minimum_decimal * window).to_integral_value(rounding=ROUND_HALF_EVEN))
        return {"signed_blocks_window": window, "minimum_signed_per_window": minimum,
                "allowed_missed_threshold": window - required,
                "downtime_jail_duration": _text(_field(params, "downtime_jail_duration"), "downtime jail duration", 64),
                "double_sign_slash_fraction": _decimal(_field(params, "slash_fraction_double_sign"), "double sign slash fraction"),
                "downtime_slash_fraction": _decimal(_field(params, "slash_fraction_downtime"), "downtime slash fraction")}

    async def _distribution(self):
        params_payload, pool = await self._rest_many((
            ("distribution_params", "/cosmos/distribution/v1beta1/params"),
            ("community_pool", "/cosmos/distribution/v1beta1/community_pool"),
        ))
        params = _mapping(params_payload.get("params"), "distribution params")
        amounts = _coins(pool.get("pool"), tuple(asset.base for asset in self.definition.assets))
        result = {"community_tax": _decimal(params.get("community_tax"), "community tax"),
                  "withdraw_address_enabled": _boolean(params.get("withdraw_addr_enabled"), "withdraw address enabled"),
                  "community_pool": amounts, "nakamoto_bonus": None}
        bonus = params.get("nakamoto_bonus")
        if bonus is not None:
            bonus = _mapping(bonus, "Nakamoto Bonus")
            result["nakamoto_bonus"] = {
                "enabled": _boolean(bonus.get("enabled"), "Nakamoto Bonus enabled"),
                "step": _decimal(bonus.get("step"), "Nakamoto Bonus step"),
                "period_epoch_identifier": _text(bonus.get("period_epoch_identifier"), "Nakamoto Bonus period", 64),
                "minimum_coefficient": _decimal(
                    bonus.get("minimum_coefficient", bonus.get("min_nakamoto_coefficient")), "minimum coefficient"),
                "maximum_coefficient": _decimal(
                    bonus.get("maximum_coefficient", bonus.get("max_nakamoto_coefficient")), "maximum coefficient")}
        return result

    async def _governance(self):
        payload = await self._rest("gov_params", "/cosmos/gov/v1/params/voting")
        params = _mapping(payload.get("params"), "governance params")
        deposits = params.get("min_deposit")
        minimum = _coins(deposits, tuple(asset.base for asset in self.definition.assets))
        advanced_names = ("law_quorum", "law_threshold", "constitution_amendment_quorum",
                          "constitution_amendment_threshold", "quorum_timeout",
                          "max_voting_period_extension", "governor_status_change_period",
                          "min_governor_self_delegation", "quorum_range", "law_quorum_range",
                          "constitution_amendment_quorum_range")
        normalized_advanced = None
        if any(name in params for name in advanced_names):
            normalized_advanced = {}
            for name in ("law_quorum", "law_threshold", "constitution_amendment_quorum", "constitution_amendment_threshold"):
                normalized_advanced[name] = _decimal(params.get(name), name) if params.get(name) is not None else None
            for public, source in (("quorum_timeout", "quorum_timeout"),
                                   ("maximum_voting_period_extension", "max_voting_period_extension"),
                                   ("governor_status_change_period", "governor_status_change_period")):
                normalized_advanced[public] = _text(params.get(source), public, 64) if params.get(source) is not None else None
            raw_self = params.get("min_governor_self_delegation")
            normalized_advanced["minimum_governor_self_delegation"] = (
                _decimal(raw_self, "minimum governor self delegation") if raw_self is not None else None)
            for name in ("quorum_range", "law_quorum_range", "constitution_amendment_quorum_range"):
                raw_range = params.get(name)
                normalized_advanced[name] = None if raw_range is None else {
                    "min": _decimal(_mapping(raw_range, name).get("min"), f"{name} minimum"),
                    "max": _decimal(raw_range.get("max"), f"{name} maximum")}
        return {"minimum_deposit": minimum,
                "maximum_deposit_period": _text(params.get("max_deposit_period"), "maximum deposit period", 64),
                "voting_period": _text(params.get("voting_period"), "voting period", 64),
                "quorum": _decimal(params.get("quorum"), "quorum"),
                "threshold": _decimal(params.get("threshold"), "threshold"),
                "advanced": normalized_advanced}

    async def _paginate(self, name, path, field):
        items = []
        next_key = ""
        for page in range(MAX_PAGES):
            separator = "&" if "?" in path else "?"
            suffix = f"{separator}pagination.limit={PAGE_SIZE}"
            if next_key:
                suffix += "&pagination.key=" + quote(next_key, safe="")
            payload = await self._rest(f"{name}_{page}_{next_key}", path + suffix)
            values = payload.get(field)
            if not isinstance(values, list) or len(values) > PAGE_SIZE:
                raise MalformedUpstreamResponse(f"invalid {field}")
            items.extend(values)
            pagination = payload.get("pagination") or {}
            if not isinstance(pagination, dict):
                raise MalformedUpstreamResponse("invalid pagination")
            raw_next = pagination.get("next_key") or ""
            if not isinstance(raw_next, str) or len(raw_next) > 1024:
                raise MalformedUpstreamResponse("invalid pagination key")
            if not raw_next:
                return items
            next_key = raw_next
        raise MalformedUpstreamResponse("pagination limit exceeded")

    async def _top_missed(self, allowed_missed_threshold: int, validators: list):
        infos = await self._paginate("signing_infos", "/cosmos/slashing/v1beta1/signing_infos", "info")
        bonded = {}
        for validator in validators:
            item = _mapping(validator, "validator")
            if item.get("status") not in (None, "BOND_STATUS_BONDED"):
                continue
            address = consensus_address(item.get("consensus_pubkey"), self.definition.validator_consensus_prefix)
            description = _mapping(item.get("description"), "validator description")
            operator_address = _text(item.get("operator_address"), "operator address", 90)
            raw_moniker = description.get("moniker")
            moniker = raw_moniker.strip() if isinstance(raw_moniker, str) else ""
            if len(moniker) > 256 or (moniker and not moniker.isprintable()):
                moniker = ""
            bonded[address] = {"moniker": moniker or operator_address,
                               "operator_address": operator_address,
                               "consensus_address": address, "jailed": _boolean(item.get("jailed"), "jailed")}
        results = []
        for raw in infos:
            info = _mapping(raw, "signing info")
            address = info.get("address")
            if address not in bonded:
                continue
            missed = _integer(info.get("missed_blocks_counter"), "missed blocks counter")
            results.append({**bonded[address], "missed_blocks_counter": missed,
                            "start_height": _integer(info.get("start_height"), "start height"),
                            "index_offset": _integer(info.get("index_offset"), "index offset"),
                            "tombstoned": _boolean(info.get("tombstoned"), "tombstoned"),
                            "remaining_misses_before_threshold": max(0, allowed_missed_threshold - missed)})
        return sorted(results, key=lambda item: (-item["missed_blocks_counter"], item["operator_address"], item["consensus_address"]))[:6]

    async def overview(self) -> dict:
        status = await self.adapter.node_status()
        supply_task = asyncio.create_task(self._supply())
        validators_task = asyncio.create_task(self._bonded_validators())
        slashing_task = asyncio.create_task(self._slashing())
        async def staking_loader():
            return await self._staking(await supply_task, await validators_task)
        section_loaders = {"assets_and_supply": supply_task, "staking": staking_loader(), "mint": self._mint(),
                           "slashing": slashing_task, "distribution": self._distribution(), "governance": self._governance()}
        names = tuple(section_loaders)
        results = await asyncio.gather(self._node_versions(), *section_loaders.values(), return_exceptions=True)
        versions, section_results = results[0], results[1:]
        if isinstance(versions, BaseException):
            versions = {}
        else:
            status = replace(status, **versions)
        normalized = {}
        failed = isinstance(results[0], BaseException)
        section_models = {"assets_and_supply": AssetsSupply, "staking": Staking, "mint": Mint,
                          "slashing": Slashing, "distribution": Distribution, "governance": Governance}
        for name, result in zip(names, section_results):
            if isinstance(result, BaseException):
                normalized[name] = {"error": {"code": "section_unavailable"}}
                failed = True
            else:
                try:
                    normalized[name] = section_models[name].model_validate(result).model_dump(mode="json")
                except ValidationError:
                    normalized[name] = {"error": {"code": "section_unavailable"}}
                    failed = True
        slashing = normalized.get("slashing", {})
        if "allowed_missed_threshold" in slashing:
            try:
                validators = await validators_task
                ranking = await self._top_missed(slashing["allowed_missed_threshold"], validators)
                normalized["top_active_validators_by_missed_blocks"] = TypeAdapter(
                    list[MissedValidator]).validate_python(ranking)
            except Exception:
                normalized["top_active_validators_by_missed_blocks"] = {"error": {"code": "section_unavailable"}}
                failed = True
        else:
            normalized["top_active_validators_by_missed_blocks"] = {"error": {"code": "section_unavailable"}}
        state = "syncing" if status.catching_up else "degraded" if failed else "healthy"
        network = {"network_id": self.definition.transport.network_id, "family": self.definition.family,
            "display_name": self.definition.display_name, "network_name": self.definition.network_name,
            "chain_id": status.chain_id, "operational_state": state, "current_local_height": status.local_height,
            "latest_block_time": status.latest_block_time, "catching_up": status.catching_up, "tx_index": status.tx_index,
            "node_version": status.node_version, "application_name": status.application_name,
            "application_version": status.application_version, "sdk_version": status.sdk_version,
            "cometbft_version": status.cometbft_version,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "block_history_state": "unknown", "historical_state": "unknown"}
        return OverviewResponse.model_validate({"network": network, **normalized}).model_dump(mode="json")

    async def market(self) -> dict:
        key = (self.definition.transport.network_id, "market", ())
        async def load():
            identifier = self.definition.coingecko_id
            response = await self.transport.get_object("https://api.coingecko.com",
                f"/api/v3/simple/price?ids={identifier}&vs_currencies=usd&include_market_cap=true&include_24hr_change=true&include_last_updated_at=true")
            item = _mapping(response.get(identifier), "market data")
            def number(name, *, nonnegative=False):
                value = item.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise MalformedUpstreamResponse("invalid market value")
                if nonnegative and value < 0:
                    raise MalformedUpstreamResponse("invalid market value")
                return format(Decimal(str(value)), "f")
            updated = _integer(item.get("last_updated_at"), "market timestamp")
            try:
                timestamp = datetime.fromtimestamp(updated, timezone.utc).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                raise MalformedUpstreamResponse("invalid market timestamp") from None
            result = {"network_id": self.definition.transport.network_id, "currency": "USD",
                      "price": number("usd", nonnegative=True),
                      "market_cap": number("usd_market_cap", nonnegative=True),
                      "change_24h": number("usd_24h_change"), "source_last_updated_at": timestamp}
            try:
                return MarketResponse.model_validate(result).model_dump(mode="json")
            except ValidationError:
                raise MalformedUpstreamResponse("invalid market data") from None
        return await self.cache.get_or_load(key, MARKET_TTL, load)
