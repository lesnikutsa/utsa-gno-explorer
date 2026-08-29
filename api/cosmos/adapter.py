"""Endpoint discovery, deterministic selection, and bounded failover."""

from dataclasses import dataclass
import logging
from urllib.parse import urlsplit

from .cache import RequestCache
from .config import CosmosNetworkConfig
from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse, RejectedEndpoint
from .parsing import parse_rest_block, parse_rest_head, parse_rpc_block, parse_rpc_status
from .transport import JsonTransport

LOGGER = logging.getLogger(__name__)
REST_LATEST_BLOCK = "/cosmos/base/tendermint/v1beta1/blocks/latest"


@dataclass(frozen=True)
class _Candidate:
    endpoint: str
    height: int
    latency: float
    order: int


class CosmosAdapter:
    def __init__(self, config: CosmosNetworkConfig, *, client=None, transport=None, cache=None, clock=None):
        self.config = config
        self._clock = clock or __import__("time").monotonic
        self._transport = JsonTransport(timeout=config.request_timeout,
                                        max_response_bytes=config.max_response_bytes,
                                        client=client, transport=transport)
        self._cache = cache or RequestCache(clock=self._clock)

    async def aclose(self):
        await self._transport.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.aclose()

    @staticmethod
    def _host(endpoint: str) -> str:
        return urlsplit(endpoint).hostname or "invalid"

    @staticmethod
    def _reason(exc: Exception) -> str:
        if isinstance(exc, RejectedEndpoint):
            code = exc.args[0] if exc.args else "rejected"
            return code if code in {"catching_up", "http_status", "transport_error", "wrong_chain", "wrong_height"} else "rejected"
        if isinstance(exc, MalformedUpstreamResponse):
            return "malformed_response"
        return "unexpected_response"

    async def _candidates(self, kind: str) -> tuple[_Candidate, ...]:
        endpoints = self.config.rpc_endpoints if kind == "rpc" else self.config.rest_endpoints
        candidates = []
        for order, endpoint in enumerate(endpoints):
            started = self._clock()
            try:
                payload = await self._transport.get_object(endpoint, "/status" if kind == "rpc" else REST_LATEST_BLOCK)
                if kind == "rpc":
                    head = parse_rpc_status(payload, network_id=self.config.network_id,
                                            expected_chain_id=self.config.chain_id, source_host=self._host(endpoint))
                    if head.catching_up:
                        raise RejectedEndpoint("catching_up")
                else:
                    head = parse_rest_head(payload, network_id=self.config.network_id,
                                           expected_chain_id=self.config.chain_id, source_host=self._host(endpoint))
                candidates.append(_Candidate(endpoint, head.latest_height, max(0.0, self._clock() - started), order))
            except Exception as exc:
                LOGGER.info("cosmos_endpoint_rejected host=%s network=%s operation=%s reason=%s candidate=%d duration_ms=%d",
                            self._host(endpoint), self.config.network_id, f"{kind}_probe", self._reason(exc),
                            order + 1, int(max(0.0, self._clock() - started) * 1000))
        if not candidates:
            raise AllEndpointsUnavailable(f"no validated {kind.upper()} endpoint")
        highest = max(item.height for item in candidates)
        fresh = [item for item in candidates if highest - item.height <= self.config.max_height_lag]
        if not fresh:
            raise AllEndpointsUnavailable(f"no fresh {kind.upper()} endpoint")
        return tuple(sorted(fresh, key=lambda item: (item.latency, item.order)))

    async def _cached_candidates(self, kind: str):
        key = (self.config.network_id, "endpoint_candidates", (kind,))
        return await self._cache.get_or_load(key, self.config.probe_ttl, lambda: self._candidates(kind))

    async def chain_head(self):
        key = (self.config.network_id, "chain_head", ())
        async def load():
            candidates = await self._cached_candidates("rpc")
            for number, candidate in enumerate(candidates, 1):
                try:
                    payload = await self._transport.get_object(candidate.endpoint, "/status")
                    return parse_rpc_status(payload, network_id=self.config.network_id,
                                            expected_chain_id=self.config.chain_id,
                                            source_host=self._host(candidate.endpoint))
                except Exception:
                    LOGGER.info("cosmos_endpoint_failed host=%s network=%s operation=chain_head reason=read_failed candidate=%d duration_ms=0",
                                self._host(candidate.endpoint), self.config.network_id, number)
            raise AllEndpointsUnavailable("all validated RPC endpoints failed")
        return await self._cache.get_or_load(key, self.config.cache_ttl, load)

    async def block(self, height: int, *, source: str = "rpc"):
        if type(height) is not int or height <= 0:
            raise ValueError("height must be a positive integer")
        if source not in {"rpc", "rest"}:
            raise ValueError("source must be RPC or REST")
        key = (self.config.network_id, "block", (source, height))
        async def load():
            candidates = await self._cached_candidates(source)
            path = f"/block?height={height}" if source == "rpc" else f"/cosmos/base/tendermint/v1beta1/blocks/{height}"
            parser = parse_rpc_block if source == "rpc" else parse_rest_block
            for number, candidate in enumerate(candidates, 1):
                try:
                    payload = await self._transport.get_object(candidate.endpoint, path)
                    result = parser(payload, network_id=self.config.network_id, expected_chain_id=self.config.chain_id)
                    if result.height != height:
                        raise RejectedEndpoint("wrong_height")
                    return result
                except Exception:
                    LOGGER.info("cosmos_endpoint_failed host=%s network=%s operation=%s_block reason=read_failed candidate=%d duration_ms=0",
                                self._host(candidate.endpoint), self.config.network_id, source, number)
            raise AllEndpointsUnavailable(f"all validated {source.upper()} endpoints failed")
        return await self._cache.get_or_load(key, self.config.cache_ttl, load)
