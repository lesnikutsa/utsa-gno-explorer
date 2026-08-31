"""Endpoint discovery, deterministic selection, and bounded failover."""

from dataclasses import dataclass
import logging
import re
from urllib.parse import urlsplit

from .cache import RequestCache
from .config import CosmosNetworkConfig
from .errors import (AllEndpointsUnavailable, HistoryUnavailable,
                     MalformedUpstreamResponse, NodeNotSynced, RejectedEndpoint)
from .parsing import (parse_node_status, parse_rest_block, parse_rest_head,
                      parse_rpc_block, parse_rpc_status)
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
            return code if code in {"catching_up", "http_status", "stale_height", "transport_error", "wrong_chain", "wrong_height"} else "rejected"
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
            minimum_fresh_height = max(candidate.height for candidate in candidates) - self.config.max_height_lag
            for number, candidate in enumerate(candidates, 1):
                started = self._clock()
                try:
                    payload = await self._transport.get_object(candidate.endpoint, "/status")
                    head = parse_rpc_status(payload, network_id=self.config.network_id,
                                            expected_chain_id=self.config.chain_id,
                                            source_host=self._host(candidate.endpoint))
                    if head.catching_up:
                        raise RejectedEndpoint("catching_up")
                    if head.latest_height < minimum_fresh_height:
                        raise RejectedEndpoint("stale_height")
                    return head
                except Exception as exc:
                    LOGGER.info("cosmos_endpoint_failed host=%s network=%s operation=chain_head reason=%s candidate=%d duration_ms=%d",
                                self._host(candidate.endpoint), self.config.network_id,
                                self._reason(exc), number,
                                int(max(0.0, self._clock() - started) * 1000))
            raise AllEndpointsUnavailable("all validated RPC endpoints failed")
        return await self._cache.get_or_load(key, self.config.cache_ttl, load)

    async def node_status(self):
        """Return identity-checked local status, including a syncing endpoint."""
        key = (self.config.network_id, "node_status", ())
        async def load():
            syncing = None
            for number, endpoint in enumerate(self.config.rpc_endpoints, 1):
                started = self._clock()
                try:
                    payload = await self._transport.get_object(endpoint, "/status")
                    status = parse_node_status(payload, network_id=self.config.network_id,
                                               expected_chain_id=self.config.chain_id,
                                               source_host=self._host(endpoint))
                    if not status.catching_up:
                        return status
                    syncing = syncing or status
                except Exception as exc:
                    LOGGER.info("cosmos_endpoint_failed host=%s network=%s operation=node_status reason=%s candidate=%d duration_ms=%d",
                                self._host(endpoint), self.config.network_id, self._reason(exc), number,
                                int(max(0.0, self._clock() - started) * 1000))
            if syncing is not None:
                return syncing
            raise AllEndpointsUnavailable("no identity-validated RPC status")
        return await self._cache.get_or_load(key, 2.0, load)

    async def rest_failover(self, path: str):
        """Fetch a validated REST resource, rejecting malformed candidates in the caller."""
        candidates = await self._cached_candidates("rest")
        failures = []
        for candidate in candidates:
            try:
                yield candidate.endpoint, await self._transport.get_object(
                    candidate.endpoint, path, accept_error_payload=True)
            except Exception as exc:
                failures.append(exc)
        if failures and len(failures) == len(candidates):
            raise AllEndpointsUnavailable("all validated REST endpoints failed")

    async def block(self, height: int, *, source: str = "rpc"):
        if type(height) is not int or height <= 0:
            raise ValueError("height must be a positive integer")
        if source not in {"rpc", "rest"}:
            raise ValueError("source must be RPC or REST")
        key = (self.config.network_id, "block", (source, height))
        async def load():
            syncing_only = False
            try:
                candidates = await self._cached_candidates(source)
            except AllEndpointsUnavailable:
                if source != "rpc":
                    raise
                status_candidates = []
                for order, endpoint in enumerate(self.config.rpc_endpoints):
                    try:
                        payload = await self._transport.get_object(endpoint, "/status")
                        status = parse_node_status(payload, network_id=self.config.network_id,
                                                   expected_chain_id=self.config.chain_id,
                                                   source_host=self._host(endpoint))
                        if status.catching_up:
                            status_candidates.append(_Candidate(endpoint, status.local_height, 0.0, order))
                    except Exception:
                        continue
                if not status_candidates:
                    raise
                syncing_only = True
                candidates = tuple(status_candidates)
                if all(candidate.height < height for candidate in candidates):
                    raise NodeNotSynced("node_not_synced")
            path = f"/block?height={height}" if source == "rpc" else f"/cosmos/base/tendermint/v1beta1/blocks/{height}"
            parser = parse_rpc_block if source == "rpc" else parse_rest_block
            history_observations = []
            for number, candidate in enumerate(candidates, 1):
                if syncing_only and candidate.height < height:
                    continue
                started = self._clock()
                try:
                    payload = await self._transport.get_object(candidate.endpoint, path,
                                                               accept_error_payload=source == "rpc")
                    if source == "rpc" and isinstance(payload.get("error"), dict):
                        message = payload["error"].get("data") or payload["error"].get("message")
                        match = re.search(r"height\s+\d+\s+is not available(?:, lowest height is\s+(\d+))?",
                                          message if isinstance(message, str) else "", re.IGNORECASE)
                        if match:
                            raise HistoryUnavailable(height, int(match.group(1)) if match.group(1) else None)
                    result = parser(payload, network_id=self.config.network_id, expected_chain_id=self.config.chain_id)
                    if result.height != height:
                        raise RejectedEndpoint("wrong_height")
                    return result
                except HistoryUnavailable as exc:
                    history_observations.append(exc.lowest_available_height)
                    continue
                except Exception as exc:
                    LOGGER.info("cosmos_endpoint_failed host=%s network=%s operation=%s_block reason=%s candidate=%d duration_ms=%d",
                                self._host(candidate.endpoint), self.config.network_id, source,
                                self._reason(exc), number,
                                int(max(0.0, self._clock() - started) * 1000))
            if history_observations:
                known = [item for item in history_observations if item is not None]
                raise HistoryUnavailable(height, min(known) if known else None)
            raise AllEndpointsUnavailable(f"all validated {source.upper()} endpoints failed")
        return await self._cache.get_or_load(key, self.config.cache_ttl, load)
