"""Request-driven, strictly normalized Cosmos overview aggregation."""

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import hashlib
import math
import re
from urllib.parse import quote, urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from .adapter import CosmosAdapter
from .cache import RequestCache
from .errors import (AllEndpointsUnavailable, InvalidValidatorAddress, MalformedUpstreamResponse,
                     RejectedEndpoint, TransactionNotFound, ValidatorNotFound)
from .parsing import parse_node_status, parse_rest_node_info, parse_rpc_block
from .registry import NetworkDefinition
from .schemas import (AssetsSupply, Distribution, Governance, MarketHistoryResponse, MarketResponse,
                      CosmosTransactionsResponse, CosmosValidatorDelegationsResponse,
                      CosmosValidatorActivityResponse,
                      CosmosValidatorDetail, MissedValidator, Mint,
                      OverviewResponse, Slashing, Staking, CosmosValidatorsResponse)
from .blocks import checkpoint_average, metadata
from .block_detail import normalize_detail
from .rfc3339 import parse_rfc3339
from .errors import HistoryUnavailable
from .transactions import normalize_transactions
from .transaction_detail import normalize_transaction_detail
from .validators import (approximate_token_delta, category, category_voting_power_rank, miss_metrics,
                         aggregate_commit, signing_height_range, target_height_24h)
from .validator_activity import event_queries, merge_activity, MAX_ACTIVITY

SECTION_TTL = 5.0
MARKET_TTL = 30.0
ETA_SAMPLE_TTL = 300.0
MAX_PAGES = 10
PAGE_SIZE = 200
MAX_LIST_ITEMS = MAX_PAGES * PAGE_SIZE
_UNSIGNED_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_SIGNED_DECIMAL = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")
_QUERY_FIELD_UNSUPPORTED = re.compile(
    r"(?:unknown|unsupported|unrecognized|cannot find|no such)\s+(?:query\s+)?(?:parameter|field)?\s*[`'\"]?query",
    re.IGNORECASE,
)


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


def validator_reward_coins(payload: object, wrapper: str) -> list[dict[str, str]]:
    """Preserve every valid coin from an optional distribution response."""
    if isinstance(payload, BaseException) or not isinstance(payload, dict):
        return []
    container = payload.get(wrapper)
    coins = container.get(wrapper) if isinstance(container, dict) else None
    if not isinstance(coins, list):
        return []
    result = []
    for coin in coins:
        if not isinstance(coin, dict):
            continue
        denom = coin.get("denom")
        if not isinstance(denom, str) or not denom or len(denom) > 128:
            continue
        try:
            amount = _decimal(coin.get("amount"), "validator reward")
        except MalformedUpstreamResponse:
            continue
        result.append({"denom": denom, "amount": amount})
    return result


def validator_reward_amount(payload: object, wrapper: str, denom: str) -> str | None:
    """Read one native-denom amount from an optional distribution response."""
    coin = next((item for item in validator_reward_coins(payload, wrapper)
                 if item["denom"] == denom), None)
    return coin["amount"] if coin else None


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


def valid_bech32_address(value: str, prefix: str) -> bool:
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    if not isinstance(value, str) or value.lower() != value or not value.startswith(prefix + "1") or len(value) > 90:
        return False
    payload = value[len(prefix) + 1:]
    if len(payload) < 7 or any(char not in charset for char in payload):
        return False
    expanded = [ord(char) >> 5 for char in prefix] + [0] + [ord(char) & 31 for char in prefix]
    return _bech32_polymod(expanded + [charset.index(char) for char in payload]) == 1


def reencode_bech32_address(value: str, source_prefix: str, target_prefix: str) -> str:
    """Re-encode the same Bech32 payload with another configured registry prefix."""
    if not valid_bech32_address(value, source_prefix):
        raise InvalidValidatorAddress("invalid validator operator address")
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    words = [charset.index(char) for char in value[len(source_prefix) + 1:-6]]
    expanded = [ord(char) >> 5 for char in target_prefix] + [0] + [ord(char) & 31 for char in target_prefix]
    polymod = _bech32_polymod(expanded + words + [0] * 6) ^ 1
    checksum = [(polymod >> 5 * (5 - index)) & 31 for index in range(6)]
    return target_prefix + "1" + "".join(charset[item] for item in words + checksum)


class CosmosService:
    def __init__(self, definition: NetworkDefinition, *, client: httpx.AsyncClient,
                 cache: RequestCache, wall_clock=None):
        self.definition = definition
        self.cache = cache
        self._client = client
        self.adapter = CosmosAdapter(definition.transport, client=client, cache=cache)
        self.transport = self.adapter._transport
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._signing_strip = {}
        self._signing_height = 0
        self._signing_warmup = None
        self._signing_blocks = {}
        self._validator_sets_by_hash = {}
        self._avatars = {}
        self._avatar_tasks = {}

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
        try:
            identities = self._validator_identities(await self._bonded_validators())
        except Exception:
            identities = {}
        enriched = []
        for item in items:
            identity = identities.get(item["proposer"].upper())
            enriched.append({**item, **identity,
                "proposer_avatar_url": self._avatar(identity.get("proposer_identity"))} if identity else item)
        return {"source": "rpc_metadata", "blocks": sorted(enriched, key=lambda item: item["height"], reverse=True)[:limit]}

    async def transactions(self, limit=20, page=1):
        # Future list fallback: evaluate a separately bounded recent-block scan
        # (blocks -> tx bytes -> block_results) before exposing this capability.
        if type(limit) is not int or not 1 <= limit <= 20 or type(page) is not int or not 1 <= page <= 100:
            raise ValueError("invalid transaction page")
        path = ("/cosmos/tx/v1beta1/txs?events=tx.height%3E0"
                f"&pagination.offset={(page - 1) * limit}&pagination.limit={limit}&pagination.count_total=true"
                "&order_by=ORDER_BY_DESC")
        capability = False
        async for endpoint, payload in self.adapter.rest_failover(path):
            if "code" in payload and "tx" in str(payload.get("message", "")).lower():
                capability = True
                continue
            try:
                rows, total = normalize_transactions(payload, limit)
                candidate = {"state": "available", "transactions": rows, "page": page,
                        "page_size": limit, "total": total,
                        "has_older": page < 100 and total is not None and page * limit < total,
                        "has_newer": page > 1, "source_host": self.adapter._host(endpoint)}
                return TypeAdapter(CosmosTransactionsResponse).validate_python(candidate).model_dump()
            except (MalformedUpstreamResponse, ValidationError):
                continue
        if capability:
            return {"state": "indexing_unavailable", "transactions": [], "page": page,
                    "page_size": limit, "total": None, "has_older": False, "has_newer": page > 1}
        raise AllEndpointsUnavailable("no valid transaction search response")

    async def transaction_lookup(self, tx_hash: str):
        """Resolve an exact transaction hash through identity-validated RPCs."""
        if not isinstance(tx_hash, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", tx_hash) is None:
            raise ValueError("invalid transaction hash")
        normalized_hash = tx_hash.upper()
        candidates = await self.adapter._cached_candidates("rpc")
        not_found = False
        for candidate in candidates:
            try:
                payload = await self.transport.get_object(
                    candidate.endpoint, f"/tx?hash=0x{normalized_hash}&prove=false",
                    accept_error_payload=True)
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("data") or error.get("message") or "").lower()
                    if "not found" in message:
                        not_found = True
                    continue
                result = _mapping(payload.get("result"), "transaction lookup result")
                result_hash = _text(result.get("hash"), "transaction hash", 64).upper()
                if result_hash != normalized_hash or re.fullmatch(r"[0-9A-F]{64}", result_hash) is None:
                    raise MalformedUpstreamResponse("transaction hash mismatch")
                height = _integer(result.get("height"), "transaction height")
                index = _integer(result.get("index"), "transaction index")
                if height <= 0 or index > 10_000:
                    raise MalformedUpstreamResponse("invalid transaction location")
                return {"height": height, "index": index, "tx_hash": result_hash}
            except Exception:
                continue
        if not_found:
            raise TransactionNotFound("transaction not found")
        raise AllEndpointsUnavailable("transaction lookup unavailable")

    @staticmethod
    def _validator_identities(validators):
        identities = {}
        for raw in validators:
            try:
                validator = _mapping(raw, "validator")
                public_key = _mapping(validator.get("consensus_pubkey"), "consensus public key")
                decoded = base64.b64decode(_text(public_key.get("key"), "consensus public key", 256), validate=True)
                proposer = hashlib.sha256(decoded).digest()[:20].hex().upper()
                operator = _text(validator.get("operator_address"), "operator address", 90)
                description = _mapping(validator.get("description"), "validator description")
                moniker = description.get("moniker")
                if not isinstance(moniker, str) or not moniker.strip() or len(moniker.strip()) > 256 or not moniker.isprintable():
                    continue
                raw_identity = description.get("identity")
                identity = raw_identity.strip() if isinstance(raw_identity, str) else ""
                if len(identity) > 128 or (identity and (not identity.isascii() or not identity.isalnum())):
                    identity = ""
                identities[proposer] = {"proposer_moniker": moniker.strip(), "proposer_operator_address": operator,
                                        **({"proposer_identity": identity} if identity else {})}
            except Exception:
                continue
        return identities

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
                sample = await self.cache.get_or_load(
                    (self.definition.transport.network_id, "eta_checkpoint", ()), ETA_SAMPLE_TTL,
                    lambda: checkpoint_average(self.adapter, confirmed_height))
                if sample is None:
                    raise HistoryUnavailable(confirmed_height)
                confirmed_status = max(confirmed, key=lambda status: status.local_height)
                average = sample["average_block_seconds"]
                latest_time = parse_rfc3339(confirmed_status.latest_block_time)
                if self._wall_clock() - latest_time > timedelta(seconds=max(300, average * 20)):
                    eta, reason = None, "network_stalled"
                else:
                    remaining = height - confirmed_status.local_height
                    try:
                        estimated = latest_time + timedelta(seconds=average * remaining)
                        eta = {"remaining_blocks": remaining, "average_block_seconds": average,
                               "estimated_at": estimated.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                               "sample_intervals": sample["sample_intervals"]}
                        reason = None
                    except (OverflowError, ValueError):
                        eta, reason = None, "date_overflow"
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

    async def block_detail(self, height: int):
        """Fetch full immutable detail only for a confirmed, locally available block."""
        observations = await self._status_observations()
        local_height = max(status.local_height for _endpoint, status in observations)
        if height > local_height:
            raise AllEndpointsUnavailable("block is not locally available")
        try:
            raw_identities = self._validator_identities(await self._bonded_validators())
        except Exception:
            raw_identities = {}
        identities = {key: {"moniker": value.get("proposer_moniker"),
                            "operator_address": value.get("proposer_operator_address"),
                            "identity": value.get("proposer_identity")}
                      for key, value in raw_identities.items()}

        async def load():
            for endpoint, status in sorted(observations, key=lambda item: item[1].local_height, reverse=True):
                if status.local_height < height:
                    continue
                try:
                    block, commit, results = await asyncio.gather(
                        self.transport.get_object(endpoint, f"/block?height={height}"),
                        self.transport.get_object(endpoint, f"/commit?height={height}"),
                        self.transport.get_object(endpoint, f"/block_results?height={height}"))
                    detail = normalize_detail(block, commit, results,
                        network_id=self.definition.transport.network_id,
                        expected_chain_id=self.definition.transport.chain_id,
                        requested_height=height, local_height=local_height, identities=identities)
                    proposer_identity = raw_identities.get(detail["proposer"].upper(), {})
                    detail.update(proposer_identity)
                    return detail
                except Exception:
                    continue
            raise AllEndpointsUnavailable("block detail unavailable")
        return await self.cache.get_or_load(
            (self.definition.transport.network_id, "block_detail", (height,)), 30.0, load)

    async def transaction_detail(self, height: int, index: int):
        """Decode one transaction directly from its block; no tx index is required."""
        observations = await self._status_observations()
        async def load():
            saw_index_error = False
            for endpoint, status in sorted(observations, key=lambda item: item[1].local_height, reverse=True):
                if status.local_height < height:
                    continue
                try:
                    block, results = await asyncio.gather(
                        self.transport.get_object(endpoint, f"/block?height={height}"),
                        self.transport.get_object(endpoint, f"/block_results?height={height}"))
                    return normalize_transaction_detail(block, results,
                        expected_chain_id=self.definition.transport.chain_id,
                        requested_height=height, tx_index=index)
                except IndexError:
                    saw_index_error = True
                except Exception:
                    continue
            if saw_index_error:
                raise IndexError("transaction index out of range")
            raise AllEndpointsUnavailable("transaction detail unavailable")
        return await self.cache.get_or_load(
            (self.definition.transport.network_id, "transaction_detail", (height, index)), 30.0, load)

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

    async def _all_validators(self):
        return await self._paginate("all_validators", "/cosmos/staking/v1beta1/validators", "validators")

    async def search_validators(self, query: str, limit: int = 6):
        """Search lightweight validator identities from the shared staking-set cache."""
        if not isinstance(query, str) or not 1 <= len(query) <= 128 or query != query.strip():
            raise ValueError("query must contain between 1 and 128 trimmed characters")
        if type(limit) is not int or not 1 <= limit <= 6:
            raise ValueError("limit must be between 1 and 6")
        raw = await self.cache.get_or_load(
            (self.definition.transport.network_id, "validator_set"), 15.0, self._all_validators)
        folded_query = query.casefold()
        prefix = self.definition.validator_operator_prefix + "1"
        matches = []
        for raw_item in raw:
            item = _mapping(raw_item, "validator")
            operator = _text(item.get("operator_address"), "operator address", 90)
            if not operator.startswith(prefix):
                continue
            description = item.get("description") if isinstance(item.get("description"), dict) else {}
            moniker = str(description.get("moniker") or operator)[:256]
            folded_moniker = moniker.casefold()
            if operator == query:
                rank = 0
            elif folded_moniker == folded_query:
                rank = 1
            elif folded_moniker.startswith(folded_query):
                rank = 2
            elif folded_query in folded_moniker:
                rank = 3
            elif operator.startswith(query):
                rank = 4
            else:
                continue
            matches.append((rank, folded_moniker, operator, {
                "moniker": moniker, "operator_address": operator}))
        matches.sort(key=lambda item: item[:3])
        return {"items": [item[3] for item in matches[:limit]]}

    async def _rpc_validator_set(self, height: int):
        """Fetch one bounded CometBFT validator set through validated RPC failover."""
        candidates = await self.adapter._cached_candidates("rpc")
        for candidate in candidates:
            rows = []
            try:
                for page in range(1, MAX_PAGES + 1):
                    payload = await self.transport.get_object(
                        candidate.endpoint, f"/validators?height={height}&page={page}&per_page=100",
                        accept_error_payload=True)
                    if isinstance(payload.get("error"), dict):
                        raise MalformedUpstreamResponse("validator set unavailable")
                    result = _mapping(payload.get("result"), "validator set")
                    if _integer(result.get("block_height"), "validator set height") != height:
                        raise MalformedUpstreamResponse("validator set height mismatch")
                    values = result.get("validators")
                    if not isinstance(values, list) or len(values) > 100:
                        raise MalformedUpstreamResponse("invalid validator set")
                    for value in values:
                        item = _mapping(value, "consensus validator")
                        address = _text(item.get("address"), "consensus address", 128).upper()
                        if re.fullmatch(r"[0-9A-F]{40}", address) is None:
                            raise MalformedUpstreamResponse("invalid consensus address")
                        rows.append({"address": address,
                                     "voting_power": _integer(item.get("voting_power"), "voting power")})
                    total = _integer(result.get("total"), "validator set total")
                    if total > MAX_LIST_ITEMS or len(rows) > total:
                        raise MalformedUpstreamResponse("invalid validator set total")
                    if len(rows) == total:
                        return rows
                    if not values:
                        raise MalformedUpstreamResponse("incomplete validator set")
            except Exception:
                continue
        raise AllEndpointsUnavailable("validator set unavailable")

    async def _power_change_24h(self, current_height: int, average: float | None):
        target = target_height_24h(current_height, average)
        if target is None:
            return None
        async def load():
            current, historical = await asyncio.gather(
                self._rpc_validator_set(current_height), self._rpc_validator_set(target))
            return {"current": {item["address"]: item["voting_power"] for item in current},
                    "historical": {item["address"]: item["voting_power"] for item in historical},
                    "target_height": target}
        try:
            return await self.cache.get_or_load(
                (self.definition.transport.network_id, "validator_power_24h", ()), 900.0, load)
        except Exception:
            return None

    async def _validator_set_for_hash(self, validators_hash: str, height: int):
        cached = self._validator_sets_by_hash.get(validators_hash)
        if cached is not None:
            return cached
        rows = await self._rpc_validator_set(height)
        addresses = [item["address"] for item in rows]
        self._validator_sets_by_hash[validators_hash] = addresses
        if len(self._validator_sets_by_hash) > 64:
            self._validator_sets_by_hash.pop(next(iter(self._validator_sets_by_hash)))
        return addresses

    async def _warm_signing(self, active: set[str], height: int):
        heights = signing_height_range(self._signing_height, height)
        if not heights:
            return
        if heights and (not self._signing_height or heights[0] > self._signing_height + 1):
            self._signing_strip = {}
            self._signing_blocks = {}
        candidates = await self.adapter._cached_candidates("rpc")
        for block_height in range(heights[0], heights[-1] + 2):
            if block_height in self._signing_blocks:
                continue
            for candidate in candidates:
                try:
                    payload = await self.transport.get_object(candidate.endpoint, f"/block?height={block_height}")
                    block = _mapping(_mapping(payload.get("result"), "block result").get("block"), "block")
                    header = _mapping(block.get("header"), "block header")
                    normalized_height = _integer(header.get("height"), "block height")
                    if normalized_height != block_height:
                        raise MalformedUpstreamResponse("block height mismatch")
                    self._signing_blocks[block_height] = {"header": header, "last_commit": block.get("last_commit")}
                    break
                except Exception:
                    continue
            else:
                self._signing_blocks[block_height] = None
        for participation_height in heights:
            commit = None
            block_time, validator_addresses = None, None
            try:
                block = _mapping(self._signing_blocks.get(participation_height), "participation block")
                successor = _mapping(self._signing_blocks.get(participation_height + 1), "successor block")
                header = _mapping(block.get("header"), "participation header")
                commit = _mapping(successor.get("last_commit"), "canonical last commit")
                if _integer(commit.get("height"), "commit height") != participation_height:
                    raise MalformedUpstreamResponse("last commit height mismatch")
                validators_hash = _text(header.get("validators_hash"), "validators hash", 128)
                block_time = _text(header.get("time"), "commit time", 64)
                validator_addresses = await self._validator_set_for_hash(validators_hash, participation_height)
            except Exception:
                pass
            aggregate_commit(self._signing_strip, active, commit, validator_addresses,
                             participation_height, block_time)
        for address in active:
            self._signing_strip[address] = self._signing_strip.get(address, [])[-50:]
        self._signing_blocks = {key: value for key, value in self._signing_blocks.items()
                                if key >= heights[-1] - 49}
        self._signing_height = heights[-1]

    async def _load_avatar(self, identity: str):
        url = None
        try:
            response = await self._client.get(
                "https://keybase.io/_/api/1.0/user/lookup.json",
                params={"key_suffix": identity, "fields": "pictures"}, timeout=5.0)
            response.raise_for_status()
            payload = response.json()
            users = payload.get("them") if isinstance(payload, dict) else None
            pictures = users[0].get("pictures") if isinstance(users, list) and users and isinstance(users[0], dict) else None
            candidate = pictures.get("primary", {}).get("url") if isinstance(pictures, dict) else None
            if isinstance(candidate, str) and len(candidate) <= 2048:
                parsed = urlsplit(candidate)
                if (parsed.scheme == "https" and not parsed.username and not parsed.password
                        and (parsed.hostname == "keybase.io" or
                             (parsed.hostname == "s3.amazonaws.com" and parsed.path.startswith("/keybase_processed_uploads/")))):
                    url = candidate
        except (httpx.HTTPError, ValueError):
            self._avatars[identity] = (self._wall_clock() + timedelta(hours=24), None)
        else:
            self._avatars[identity] = (self._wall_clock() + timedelta(hours=24), url)
        finally:
            self._avatar_tasks.pop(identity, None)

    def _avatar(self, identity: str | None):
        if not identity:
            return None
        cached = self._avatars.get(identity)
        if cached and cached[0] > self._wall_clock():
            return cached[1]
        # Bound cold discovery so one validator-page request cannot fan out to
        # one outbound Keybase request per validator.
        if identity not in self._avatar_tasks and len(self._avatar_tasks) < 8:
            self._avatar_tasks[identity] = asyncio.create_task(self._load_avatar(identity))
        return None

    async def validators(self):
        """Return cached generic Cosmos staking data; secondary sections are best effort."""
        raw = await self.cache.get_or_load((self.definition.transport.network_id, "validator_set"), 15.0, self._all_validators)
        pool_task = asyncio.create_task(self._rest("validator_pool", "/cosmos/staking/v1beta1/pool"))
        slashing_task = asyncio.create_task(self._slashing())
        infos_task = asyncio.create_task(self._paginate("validator_signing_infos", "/cosmos/slashing/v1beta1/signing_infos", "info"))
        status_task = asyncio.create_task(self.adapter.node_status())
        supply_task = asyncio.create_task(self._supply())
        infos = {}
        try:
            for item in await infos_task:
                if isinstance(item, dict) and isinstance(item.get("address"), str): infos[item["address"]] = item
        except Exception:
            pass
        try: slashing = await slashing_task
        except Exception: slashing = None
        try: pool = await pool_task
        except Exception: pool = {}
        validators = []
        active_hex = set()
        consensus_hex_by_operator = {}
        for raw_item in raw:
            item = _mapping(raw_item, "validator")
            operator = _text(item.get("operator_address"), "operator address", 90)
            if not operator.startswith(self.definition.validator_operator_prefix + "1"): continue
            tokens = _integer(item.get("tokens"), "validator tokens")
            pubkey = _mapping(item.get("consensus_pubkey"), "consensus public key")
            key = base64.b64decode(pubkey.get("key"), validate=True)
            consensus_hex = hashlib.sha256(key).digest()[:20].hex().upper()
            consensus_hex_by_operator[operator] = consensus_hex
            consensus = consensus_address(pubkey, self.definition.validator_consensus_prefix)
            info = infos.get(consensus, {})
            description = item.get("description") if isinstance(item.get("description"), dict) else {}
            commission = item.get("commission") if isinstance(item.get("commission"), dict) else {}
            rates = commission.get("commission_rates") if isinstance(commission.get("commission_rates"), dict) else {}
            kind = category(item)
            liveness = None
            if kind == "active":
                active_hex.add(consensus_hex)
                missed = int(info.get("missed_blocks_counter", 0)) if info else None
                liveness = {"missed_blocks": missed} if missed is not None and slashing else None
            identity = (str(description.get("identity"))[:128]
                        if isinstance(description.get("identity"), str) and description.get("identity").isascii()
                        and description.get("identity").isalnum() else None)
            validators.append({"operator_address": operator, "consensus_address": consensus,
                "category": kind, "jailed": item.get("jailed") is True,
                "moniker": str(description.get("moniker") or operator)[:256],
                "identity": identity, "avatar_url": self._avatar(identity),
                "tokens": str(tokens), "stake_share": 0, "change_24h": None,
                "change_24h_percent": None,
                "commission": str(rates.get("rate") or "0"), "liveness": liveness,
                "jailed_until": info.get("jailed_until"), "tombstoned": info.get("tombstoned"),
                "missed_blocks": info.get("missed_blocks_counter")})
        total_bonded = sum(int(item["tokens"]) for item in validators if item["category"] == "active")
        for item in validators:
            item["stake_share"] = float(Decimal(item["tokens"]) * 100 / total_bonded) if total_bonded else 0
        try: head = await status_task
        except Exception: head = None
        average = None
        if head:
            try:
                sample = await self.cache.get_or_load(
                    (self.definition.transport.network_id, "eta_checkpoint", ()), ETA_SAMPLE_TTL,
                    lambda: checkpoint_average(self.adapter, head.local_height))
                average = sample["average_block_seconds"] if sample else None
            except Exception:
                pass
        power_change = await self._power_change_24h(head.local_height, average) if head else None
        bonded_change = None
        if power_change:
            current_total_power = sum(power_change["current"].values())
            historical_total_power = sum(power_change["historical"].values())
            aggregate_delta = approximate_token_delta(total_bonded, current_total_power, historical_total_power)
            bonded_change = str(aggregate_delta) if aggregate_delta is not None else None
            for item in validators:
                address = consensus_hex_by_operator[item["operator_address"]]
                current_power = power_change["current"].get(address)
                historical_power = power_change["historical"].get(address)
                delta = approximate_token_delta(int(item["tokens"]), current_power or 0, historical_power)
                if delta is not None:
                    item["change_24h"] = str(delta)
                    item["change_24h_percent"] = (None if historical_power == 0 else
                        float(Decimal(current_power - historical_power) * 100 / historical_power))
        for item in validators:
            if item["liveness"] is not None:
                item["liveness"] = {"missed_blocks": item["liveness"]["missed_blocks"],
                    **miss_metrics(item["liveness"]["missed_blocks"], slashing["signed_blocks_window"],
                                 slashing["minimum_signed_per_window"], average)}
        if (head and (self._signing_warmup is None or self._signing_warmup.done())
                and self._signing_height < head.local_height - 1):
            self._signing_warmup = asyncio.create_task(self._warm_signing(active_hex, head.local_height))
        for item in validators:
            if item["category"] == "active": item["signing_strip"] = self._signing_strip.get(
                consensus_hex_by_operator[item["operator_address"]], [])
        asset = self.definition.assets[0]
        bonded_ratio = None
        try:
            supply = await supply_task
            bonded = Decimal(_field(pool, "bonded_tokens"))
            total_supply = next(Decimal(value["total_supply"]) for value in supply["assets"] if value["base"] == asset.base)
            bonded_ratio = float(bonded / total_supply) if total_supply else 0.0
        except Exception:
            pass
        response = {"network_id": self.definition.transport.network_id, "asset": asset.public(),
            "summary": {"active_validators": sum(v["category"] == "active" for v in validators),
                "bonded_tokens": str(total_bonded), "bonded_ratio": bonded_ratio,
                "bonded_change_24h": bonded_change},
            "signing_history_state": "ready" if self._signing_height else "warming", "validators": validators}
        return TypeAdapter(CosmosValidatorsResponse).validate_python(response).model_dump()

    async def validator_detail(self, operator_address: str):
        """Build one validator view from the cached list and its cached staking record."""
        if not valid_bech32_address(operator_address, self.definition.validator_operator_prefix):
            raise InvalidValidatorAddress("invalid validator operator address")
        response = await self.validators()
        validator = next((item for item in response["validators"]
                          if item["operator_address"] == operator_address), None)
        if validator is None:
            raise ValidatorNotFound("validator not found")
        raw = await self.cache.get_or_load((self.definition.transport.network_id, "validator_set"), 15.0, self._all_validators)
        source = next((_mapping(item, "validator") for item in raw
                       if isinstance(item, dict) and item.get("operator_address") == operator_address), None)
        if source is None:
            raise ValidatorNotFound("validator not found")
        description = source.get("description") if isinstance(source.get("description"), dict) else {}
        commission = source.get("commission") if isinstance(source.get("commission"), dict) else {}
        rates = commission.get("commission_rates") if isinstance(commission.get("commission_rates"), dict) else {}
        pubkey = _mapping(source.get("consensus_pubkey"), "consensus public key")
        raw_pubkey = base64.b64decode(pubkey.get("key"), validate=True)
        consensus_hex = hashlib.sha256(raw_pubkey).digest()[:20].hex().upper()
        bond_status = {"BOND_STATUS_BONDED": "bonded", "BOND_STATUS_UNBONDING": "unbonding",
                       "BOND_STATUS_UNBONDED": "unbonded"}.get(source.get("status"), "unbonded")
        rewards_path = quote(operator_address, safe="")
        commission_result, rewards_result = await asyncio.gather(
            self._rest("validator_commission", f"/cosmos/distribution/v1beta1/validators/{rewards_path}/commission"),
            self._rest("validator_outstanding_rewards", f"/cosmos/distribution/v1beta1/validators/{rewards_path}/outstanding_rewards"),
            return_exceptions=True)
        asset = self.definition.assets[0]

        result = {**validator, "network_id": response["network_id"], "asset": response["asset"],
                  "signing_history_state": response["signing_history_state"],
                  "rank": category_voting_power_rank(response["validators"], validator),
                  "website": description.get("website") or None,
                  "contact": description.get("security_contact") or None,
                  "description": description.get("details") or None,
                  "account_address": reencode_bech32_address(operator_address,
                      self.definition.validator_operator_prefix, self.definition.account_prefix),
                  "hex_address": consensus_hex,
                  "evm_address": None,
                  "bond_status": bond_status,
                  "delegator_shares": _decimal(source.get("delegator_shares"), "delegator shares"),
                  "min_self_delegation": str(source.get("min_self_delegation")) if source.get("min_self_delegation") is not None else None,
                  "commission_earned": validator_reward_amount(commission_result, "commission", asset.base),
                  "delegators_total_rewards": validator_reward_amount(rewards_result, "rewards", asset.base),
                  "commission_rewards": validator_reward_coins(commission_result, "commission"),
                  "outstanding_rewards": validator_reward_coins(rewards_result, "rewards"),
                  "consensus_pubkey": pubkey.get("key"),
                  "commission": {"rate": str(rates.get("rate") or "0"),
                                 "max_rate": rates.get("max_rate"),
                                 "max_change_rate": rates.get("max_change_rate"),
                                 "update_time": commission.get("update_time")}}
        result.pop("missed_blocks", None)
        return TypeAdapter(CosmosValidatorDetail).validate_python(result).model_dump()

    async def validator_delegations(self, operator_address: str, limit: int = 10,
                                    pagination_key: str | None = None):
        """Return one live, upstream-ordered x/staking delegation page."""
        if not valid_bech32_address(operator_address, self.definition.validator_operator_prefix):
            raise InvalidValidatorAddress("invalid validator operator address")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        if pagination_key is not None:
            if (not isinstance(pagination_key, str) or not pagination_key
                    or len(pagination_key) > 512):
                raise ValueError("invalid pagination key")
            try:
                base64.b64decode(pagination_key, validate=True)
            except (ValueError, TypeError):
                raise ValueError("invalid pagination key") from None

        encoded_operator = quote(operator_address, safe="")
        query = f"pagination.limit={limit}&pagination.count_total={'true' if pagination_key is None else 'false'}"
        if pagination_key is not None:
            query += f"&pagination.key={quote(pagination_key, safe='')}"
        path = f"/cosmos/staking/v1beta1/validators/{encoded_operator}/delegations?{query}"

        def normalize(payload):
            rows = payload.get("delegation_responses") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or len(rows) > limit:
                raise MalformedUpstreamResponse("invalid delegation responses")
            items = []
            for row in rows:
                row = _mapping(row, "delegation response")
                delegation = _mapping(row.get("delegation"), "delegation")
                balance = _mapping(row.get("balance"), "delegation balance")
                delegator = _text(delegation.get("delegator_address"), "delegator address", 90)
                validator = _text(delegation.get("validator_address"), "validator address", 90)
                if (not valid_bech32_address(delegator, self.definition.account_prefix)
                        or validator != operator_address):
                    raise MalformedUpstreamResponse("invalid delegation address")
                items.append({"delegator_address": delegator, "validator_address": validator,
                    "shares": _decimal(delegation.get("shares"), "delegation shares"),
                    "balance": {"denom": _text(balance.get("denom"), "delegation denom", 128),
                                "amount": _decimal(balance.get("amount"), "delegation amount")}})
            pagination = payload.get("pagination")
            if pagination is None:
                pagination = {}
            pagination = _mapping(pagination, "delegation pagination")
            next_key = pagination.get("next_key") or None
            if next_key is not None:
                if not isinstance(next_key, str) or len(next_key) > 512:
                    raise MalformedUpstreamResponse("invalid next key")
                try:
                    base64.b64decode(next_key, validate=True)
                except (ValueError, TypeError):
                    raise MalformedUpstreamResponse("invalid next key") from None
            total = pagination.get("total") if pagination_key is None else None
            normalized = {"items": items, "next_key": next_key,
                          "total": _integer(total, "delegation total") if total is not None else None}
            return TypeAdapter(CosmosValidatorDelegationsResponse).validate_python(normalized).model_dump()

        key = (self.definition.transport.network_id, "validator_delegations",
               (operator_address, limit, pagination_key))
        async def load():
            return await self._rest("validator_delegations", path, normalize)
        return await self.cache.get_or_load(key, SECTION_TTL, load)

    async def validator_activity(self, operator_address: str, limit: int = 10, page: int = 1):
        """Merge a bounded set of live, validator-targeted transaction searches."""
        if not valid_bech32_address(operator_address, self.definition.validator_operator_prefix):
            raise InvalidValidatorAddress("invalid validator operator address")
        if type(limit) is not int or not 1 <= limit <= 10 or type(page) is not int or not 1 <= page <= 5:
            raise ValueError("invalid activity pagination")
        account_address = reencode_bech32_address(
            operator_address, self.definition.validator_operator_prefix, self.definition.account_prefix)
        upstream_limit = min(MAX_ACTIVITY, page * limit + 1)

        async def stream(key, address):
            return await self._validator_event_search(f"{key}='{address}'", upstream_limit)

        outcomes = await asyncio.gather(*(stream(*query) for query in event_queries(
            operator_address, account_address)), return_exceptions=True)
        successful = []
        account_validator = lambda address: valid_bech32_address(address, self.definition.account_prefix)
        operator_validator = lambda address: valid_bech32_address(
            address, self.definition.validator_operator_prefix)
        for item in outcomes:
            if not isinstance(item, dict):
                continue
            try:
                merge_activity([item], operator_address, account_address,
                               account_validator, operator_validator)
                successful.append(item)
            except MalformedUpstreamResponse:
                continue
        if not successful:
            result = {"state": "indexing_unavailable", "items": [], "page": page,
                      "page_size": limit, "has_more": False}
        else:
            items = merge_activity(successful, operator_address, account_address,
                                   account_validator, operator_validator)
            start = (page - 1) * limit
            result = {"state": "partial" if len(successful) < len(outcomes) else "available",
                      "items": items[start:start + limit], "page": page, "page_size": limit,
                      "has_more": start + limit < len(items)}
        return TypeAdapter(CosmosValidatorActivityResponse).validate_python(result).model_dump()

    async def _validator_event_search(self, expression: str, limit: int):
        """Use the SDK v0.50 query shape, with an explicit v0.47 compatibility fallback."""
        cache_key = (self.definition.transport.network_id, "validator_event_search", (expression, limit))

        def valid(payload):
            if not isinstance(payload, dict):
                return False
            txs, responses, pagination = (payload.get("txs"), payload.get("tx_responses"),
                                          payload.get("pagination"))
            return (isinstance(txs, list) and isinstance(responses, list)
                    and len(txs) == len(responses) and len(txs) <= limit
                    and (pagination is None or isinstance(pagination, dict)))

        def error_text(payload):
            if not isinstance(payload, dict):
                return ""
            return " ".join(str(payload.get(key, "")) for key in ("message", "details", "error"))

        async def load():
            candidates = await self.adapter._cached_candidates("rest")
            encoded = quote(expression, safe="")
            modern = (f"/cosmos/tx/v1beta1/txs?query={encoded}&order_by=ORDER_BY_DESC"
                      f"&page=1&limit={limit}")
            legacy = (f"/cosmos/tx/v1beta1/txs?events={encoded}&order_by=ORDER_BY_DESC"
                      f"&page=1&limit={limit}")
            for candidate in candidates:
                try:
                    payload = await self.transport.get_object(
                        candidate.endpoint, modern, accept_error_payload=True)
                except Exception:
                    continue
                if valid(payload):
                    return payload
                if _QUERY_FIELD_UNSUPPORTED.search(error_text(payload)) is None:
                    continue
                try:
                    fallback = await self.transport.get_object(
                        candidate.endpoint, legacy, accept_error_payload=True)
                except Exception:
                    continue
                if valid(fallback):
                    return fallback
            raise AllEndpointsUnavailable("validator event search unavailable")

        return await self.cache.get_or_load(cache_key, SECTION_TTL, load)

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
                               "consensus_address": address, "jailed": _boolean(item.get("jailed"), "jailed"),
                               "identity": (_text(description["identity"], "validator identity", 128)
                                            if isinstance(description.get("identity"), str)
                                            and description["identity"].isascii() and description["identity"].isalnum() else None)}
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
        top = sorted(results, key=lambda item: (
            -item["missed_blocks_counter"], item["operator_address"], item["consensus_address"]))[:6]
        for item in top:
            item["avatar_url"] = self._avatar(item.get("identity"))
        return top

    async def overview(self) -> dict:
        status = await self.adapter.node_status()
        try:
            rpc_candidates = await self.adapter._cached_candidates("rpc")
            highest = max(candidate.height for candidate in rpc_candidates)
            rpc_pool = [{"host": self.adapter._host(candidate.endpoint),
                         "latency_ms": min(30000, max(0, round(candidate.latency * 1000))),
                         "height": candidate.height,
                         "state": "healthy" if highest - candidate.height <= self.definition.transport.max_height_lag else "degraded",
                         "selected": self.adapter._host(candidate.endpoint) == status.source_host}
                        for candidate in rpc_candidates]
        except Exception:
            rpc_pool = []
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
            "block_history_state": "unknown", "historical_state": "unknown",
            "rpc_status_source": status.source_host, "rpc_pool": rpc_pool}
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

    async def market_history(self) -> dict:
        key = (self.definition.transport.network_id, "market_history", ())
        async def load():
            identifier = quote(self.definition.coingecko_id, safe="")
            response = await self.transport.get_object("https://api.coingecko.com",
                f"/api/v3/coins/{identifier}/market_chart?vs_currency=usd&days=1")
            prices = response.get("prices")
            if not isinstance(prices, list) or not 2 <= len(prices) <= 2000:
                raise MalformedUpstreamResponse("invalid market history")
            normalized = []
            for point in prices:
                if not isinstance(point, list) or len(point) != 2:
                    raise MalformedUpstreamResponse("invalid market history point")
                timestamp, price = point
                if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                        or not math.isfinite(timestamp) or timestamp <= 0
                        or isinstance(price, bool) or not isinstance(price, (int, float))
                        or not math.isfinite(price) or price < 0):
                    raise MalformedUpstreamResponse("invalid market history point")
                normalized.append({"timestamp": int(timestamp), "price": format(Decimal(str(price)), "f")})
            if any(right["timestamp"] <= left["timestamp"] for left, right in zip(normalized, normalized[1:])):
                raise MalformedUpstreamResponse("invalid market history order")
            if len(normalized) > 96:
                normalized = [normalized[index * (len(normalized) - 1) // 95] for index in range(96)]
            result = {"network_id": self.definition.transport.network_id, "currency": "USD", "points": normalized}
            return MarketHistoryResponse.model_validate(result).model_dump(mode="json")
        return await self.cache.get_or_load(key, MARKET_TTL, load)
