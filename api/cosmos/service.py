"""Request-driven Cosmos overview and market aggregation."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .adapter import CosmosAdapter
from .cache import RequestCache
from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse
from .registry import NetworkDefinition

SECTION_TTL = 5.0
MARKET_TTL = 30.0
MAX_LIST_ITEMS = 10_000


def _decimal(value: object, name: str, *, nonnegative: bool = True) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not value or len(value) > 128:
        raise MalformedUpstreamResponse(f"invalid {name}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise MalformedUpstreamResponse(f"invalid {name}") from None
    if not number.is_finite() or (nonnegative and number < 0):
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _integer(value: object, name: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse(f"invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 20):
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if (nonnegative and result < 0) or result > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def _coins(payload: object, allowed: frozenset[str]) -> dict[str, str]:
    if not isinstance(payload, list) or len(payload) > MAX_LIST_ITEMS:
        raise MalformedUpstreamResponse("invalid coin list")
    result = {denom: "0" for denom in allowed}
    for coin in payload:
        if not isinstance(coin, dict):
            raise MalformedUpstreamResponse("invalid coin")
        denom = coin.get("denom")
        if denom in allowed:
            result[denom] = _decimal(coin.get("amount"), "coin amount")
    return result


class CosmosService:
    def __init__(self, definition: NetworkDefinition, *, client: httpx.AsyncClient,
                 cache: RequestCache):
        self.definition = definition
        self.cache = cache
        self.adapter = CosmosAdapter(definition.transport, client=client, cache=cache)
        self.transport = self.adapter._transport

    async def _rest(self, name: str, path: str):
        key = (self.definition.transport.network_id, "overview_section", (name,))
        async def load():
            last_error = None
            for endpoint in self.definition.transport.rest_endpoints:
                try:
                    return await self.transport.get_object(endpoint, path)
                except Exception as exc:
                    last_error = exc
            raise AllEndpointsUnavailable(f"{name} unavailable") from None
        return await self.cache.get_or_load(key, SECTION_TTL, load)

    async def _supply(self):
        payload = await self._rest("supply", "/cosmos/bank/v1beta1/supply?pagination.limit=1000")
        values = _coins(payload.get("supply"), frozenset(asset.base for asset in self.definition.assets))
        return {"assets": [dict(base=a.base, display=a.display, symbol=a.symbol, exponent=a.exponent,
                                total_supply=values[a.base]) for a in self.definition.assets]}

    async def overview(self) -> dict:
        status = await self.adapter.node_status()
        sections = {
            "assets_and_supply": self._supply(),
            "staking": self._rest("staking", "/cosmos/staking/v1beta1/pool"),
            "mint": self._rest("mint", "/cosmos/mint/v1beta1/inflation"),
            "slashing": self._rest("slashing", "/cosmos/slashing/v1beta1/params"),
            "distribution": self._rest("distribution", "/cosmos/distribution/v1beta1/community_pool"),
            "governance": self._rest("governance", "/cosmos/gov/v1/params/voting"),
        }
        names = tuple(sections)
        results = await asyncio.gather(*sections.values(), return_exceptions=True)
        normalized = {}
        failed = False
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                normalized[name] = {"error": {"code": "section_unavailable"}}
                failed = True
            elif name == "assets_and_supply":
                normalized[name] = result
            else:
                # A deliberately bounded foundation: raw module payloads never cross the API.
                normalized[name] = {"state": "available"}
        state = "syncing" if status.catching_up else "degraded" if failed else "healthy"
        network = {
            "network_id": self.definition.transport.network_id,
            "family": self.definition.family, "display_name": self.definition.display_name,
            "network_name": self.definition.network_name, "chain_id": status.chain_id,
            "operational_state": state, "current_local_height": status.local_height,
            "latest_block_time": status.latest_block_time, "catching_up": status.catching_up,
            "tx_index": status.tx_index, "node_version": status.node_version,
            "application_name": status.application_name,
            "application_version": status.application_version, "sdk_version": status.sdk_version,
            "cometbft_version": status.cometbft_version,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "block_history_state": "unknown", "historical_state": "unknown",
        }
        return {"network": network, **normalized}

    async def market(self) -> dict:
        key = (self.definition.transport.network_id, "market", ())
        async def load():
            response = await self.transport.get_object(
                "https://api.coingecko.com",
                f"/api/v3/coins/{self.definition.coingecko_id}?localization=false&tickers=false&community_data=false&developer_data=false&sparkline=false",
            )
            market = response.get("market_data")
            if not isinstance(market, dict):
                raise MalformedUpstreamResponse("invalid market data")
            def usd(field):
                value = market.get(field)
                if not isinstance(value, dict): raise MalformedUpstreamResponse("invalid market data")
                item = value.get("usd")
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise MalformedUpstreamResponse("invalid market value")
                return str(item)
            changed = market.get("price_change_percentage_24h")
            if isinstance(changed, bool) or not isinstance(changed, (int, float)):
                raise MalformedUpstreamResponse("invalid market change")
            updated = response.get("last_updated")
            if not isinstance(updated, str) or len(updated) > 64:
                raise MalformedUpstreamResponse("invalid market timestamp")
            return {"network_id": self.definition.transport.network_id, "currency": "USD",
                    "price": usd("current_price"), "market_cap": usd("market_cap"),
                    "change_24h": str(changed), "source_last_updated_at": updated}
        return await self.cache.get_or_load(key, MARKET_TTL, load)
