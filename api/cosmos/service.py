"""Public Cosmos service facade with transaction-specific endpoint policy."""

import asyncio

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

    async def endpoint_status(self):
        """Return shared, bounded health for configured paired providers."""
        providers = self.definition.endpoint_providers
        canonical_id = self.definition.canonical_id or self.definition.transport.network_id
        cache_key = (canonical_id, "endpoint_provider_status", ())

        async def load():
            rpc_result, rest_result = await asyncio.gather(
                self.adapter._cached_candidates("rpc"),
                self.adapter._cached_candidates("rest"),
                return_exceptions=True,
            )
            rpc_candidates = () if isinstance(rpc_result, Exception) else tuple(rpc_result)
            rest_candidates = () if isinstance(rest_result, Exception) else tuple(rest_result)
            rpc_by_endpoint = {candidate.endpoint: candidate for candidate in rpc_candidates}
            rest_by_endpoint = {candidate.endpoint: candidate for candidate in rest_candidates}

            preferred_rpc = rpc_candidates[0].endpoint if rpc_candidates else None
            preferred_api = rest_candidates[0].endpoint if rest_candidates else None
            preferred_rpc_provider = next(
                (provider.id for provider in providers if provider.rpc_endpoint == preferred_rpc), None)
            preferred_api_provider = next(
                (provider.id for provider in providers if provider.rest_endpoint == preferred_api), None)

            rows = []
            for provider in providers:
                rpc = rpc_by_endpoint.get(provider.rpc_endpoint)
                rest = rest_by_endpoint.get(provider.rest_endpoint)
                rows.append({
                    "id": provider.id,
                    "label": provider.label,
                    "rpc": {
                        "host": self.adapter._host(provider.rpc_endpoint),
                        "state": "healthy" if rpc is not None else "unavailable",
                        "height": rpc.height if rpc is not None else None,
                        "latency_ms": min(30000, max(0, round(rpc.latency * 1000))) if rpc is not None else None,
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
