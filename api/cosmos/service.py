"""Public Cosmos service facade with transaction-specific endpoint policy."""

import asyncio
import re

from . import service_core as _core
from .service_core import *  # noqa: F401,F403
from .transaction_endpoint_policy import (
    TransactionEndpointPolicyMixin,
    _TX_HISTORY_WINDOW,
    _encode_history_cursor,
)


# The test suite (and a few focused integrations) patch these historical
# service-module symbols. Keep core method lookups routed through this facade
# so moving the unchanged implementation to service_core stays transparent.
_original_valid_bech32_address = valid_bech32_address
_original_reencode_bech32_address = reencode_bech32_address
_original_metadata = metadata

_HISTORY_FLOOR = re.compile(r"lowest height is\s+(\d+)", re.IGNORECASE)
_PROVIDER_CAPABILITY_TTL = 3600.0


def _forward_valid_bech32_address(*args, **kwargs):
    return globals()["valid_bech32_address"](*args, **kwargs)


def _forward_reencode_bech32_address(*args, **kwargs):
    return globals()["reencode_bech32_address"](*args, **kwargs)


async def _forward_metadata(*args, **kwargs):
    return await globals()["metadata"](*args, **kwargs)


_core.valid_bech32_address = _forward_valid_bech32_address
_core.reencode_bech32_address = _forward_reencode_bech32_address
_core.metadata = _forward_metadata


class CosmosService(TransactionEndpointPolicyMixin, _core.CosmosService):
    """Cosmos aggregation service with operation-aware transaction failover."""

    async def _provider_rpc_capabilities(self, provider, canonical_id: str):
        """Read slow-changing RPC capabilities with a long shared cache.

        This intentionally performs only two point requests: `/status` for the
        CometBFT tx-index flag and `/block?height=1` to learn the retained block
        floor from the normal pruning error. It never performs a tx search or a
        historical range scan.
        """
        transport = getattr(self, "transport", None)
        if transport is None:
            return {"tx_index": "unknown", "lowest_available_height": None}

        cache_key = (canonical_id, "endpoint_provider_rpc_capabilities", (provider.id,))

        async def load():
            tx_index = "unknown"
            lowest_available_height = None

            try:
                payload = await transport.get_object(provider.rpc_endpoint, "/status")
                status = _core.parse_node_status(
                    payload,
                    network_id=canonical_id,
                    expected_chain_id=self.definition.transport.chain_id,
                    source_host=self.adapter._host(provider.rpc_endpoint),
                )
                tx_index = status.tx_index
            except Exception:
                pass

            try:
                payload = await transport.get_object(
                    provider.rpc_endpoint, "/block?height=1", accept_error_payload=True)
                result = payload.get("result") if isinstance(payload, dict) else None
                block = result.get("block") if isinstance(result, dict) else None
                header = block.get("header") if isinstance(block, dict) else None
                if isinstance(header, dict) and str(header.get("height")) == "1":
                    lowest_available_height = 1
                else:
                    error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(error, dict):
                        message = error.get("data") or error.get("message") or ""
                        match = _HISTORY_FLOOR.search(str(message))
                        if match:
                            value = int(match.group(1))
                            if value > 0:
                                lowest_available_height = value
            except Exception:
                pass

            return {
                "tx_index": tx_index,
                "lowest_available_height": lowest_available_height,
            }

        return await self.cache.get_or_load(
            cache_key, _PROVIDER_CAPABILITY_TTL, load)

    async def endpoint_status(self):
        """Return shared, bounded health for configured paired providers."""
        providers = self.definition.endpoint_providers
        canonical_id = self.definition.canonical_id or self.definition.transport.network_id
        cache_key = (canonical_id, "endpoint_provider_status", ())

        async def load():
            rpc_result, rest_result, capability_result = await asyncio.gather(
                self.adapter._cached_candidates("rpc"),
                self.adapter._cached_candidates("rest"),
                asyncio.gather(*(
                    self._provider_rpc_capabilities(provider, canonical_id)
                    for provider in providers
                ), return_exceptions=True),
                return_exceptions=True,
            )
            rpc_candidates = () if isinstance(rpc_result, Exception) else tuple(rpc_result)
            rest_candidates = () if isinstance(rest_result, Exception) else tuple(rest_result)
            capabilities = () if isinstance(capability_result, Exception) else tuple(capability_result)
            rpc_by_endpoint = {candidate.endpoint: candidate for candidate in rpc_candidates}
            rest_by_endpoint = {candidate.endpoint: candidate for candidate in rest_candidates}

            preferred_rpc = rpc_candidates[0].endpoint if rpc_candidates else None
            preferred_api = rest_candidates[0].endpoint if rest_candidates else None
            preferred_rpc_provider = next(
                (provider.id for provider in providers if provider.rpc_endpoint == preferred_rpc), None)
            preferred_api_provider = next(
                (provider.id for provider in providers if provider.rest_endpoint == preferred_api), None)

            rows = []
            for index, provider in enumerate(providers):
                rpc = rpc_by_endpoint.get(provider.rpc_endpoint)
                rest = rest_by_endpoint.get(provider.rest_endpoint)
                capability = capabilities[index] if index < len(capabilities) else None
                if isinstance(capability, Exception) or not isinstance(capability, dict):
                    capability = {"tx_index": "unknown", "lowest_available_height": None}
                rows.append({
                    "id": provider.id,
                    "label": provider.label,
                    "rpc": {
                        "host": self.adapter._host(provider.rpc_endpoint),
                        "state": "healthy" if rpc is not None else "unavailable",
                        "height": rpc.height if rpc is not None else None,
                        "latency_ms": min(30000, max(0, round(rpc.latency * 1000))) if rpc is not None else None,
                        "tx_index": capability.get("tx_index", "unknown"),
                        "lowest_available_height": capability.get("lowest_available_height"),
                    },
                    "api": {
                        "host": self.adapter._host(provider.rest_endpoint),
                        "state": "healthy" if rest is not None else "unavailable",
                        "height": rest.height if rest is not None else None,
                        "latency_ms": min(30000, max(0, round(rest.latency * 1000))) if rest is not None else None,
                    },
                })

            return {
                "network_id": canonical_id,
                "mode": "manual" if self.definition.selected_provider_id else "auto",
                "selected_provider_id": self.definition.selected_provider_id,
                "preferred_rpc_provider_id": preferred_rpc_provider,
                "preferred_api_provider_id": preferred_api_provider,
                "mixed_providers": bool(
                    preferred_rpc_provider and preferred_api_provider
                    and preferred_rpc_provider != preferred_api_provider),
                "providers": rows,
            }

        # The frontend asks for this at most every 30 seconds. A shared cache
        # keeps many viewers from multiplying the same three-pair health probe.
        # Slow-changing tx-index/history-floor capabilities have their own
        # one-hour cache and never perform transaction searches.
        return await self.cache.get_or_load(cache_key, 30.0, load)

    async def _newer_history_cursor(self, anchor: int, upper: int, page: int,
                                    limit: int) -> str | None:
        """Move toward the live anchor without any additional tx-index probe.

        Historical navigation is positional: a Newer click walks one page or
        one fixed-height window toward the frozen live anchor. Empty windows
        are allowed to render empty instead of triggering hidden search scans.
        """
        if page > 1:
            target_page = page - 1
            if upper == anchor and target_page == 1:
                return None
            return _encode_history_cursor(anchor, upper, target_page)
        if upper >= anchor:
            return None
        newer_upper = min(anchor, upper + _TX_HISTORY_WINDOW)
        if newer_upper == anchor:
            return None
        return _encode_history_cursor(anchor, newer_upper, 1)

    async def _transaction_history_uncached(self, limit: int, cursor: str | None):
        result = await super()._transaction_history_uncached(limit, cursor)
        if cursor is not None and result.get("state") == "available":
            # Historical pages always have a path toward the live view. A
            # null newer_cursor intentionally means "go back to live".
            result["has_newer"] = True
        return result


def __getattr__(name):
    """Preserve imports of existing private helpers used by focused tests."""
    return getattr(_core, name)
