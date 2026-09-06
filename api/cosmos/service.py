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
_HISTORY_UNAVAILABLE = re.compile(
    r"(?:lowest height is|height[^\n]*not available|could not find[^\n]*height|pruned)",
    re.IGNORECASE,
)
_PROVIDER_CAPABILITY_TTL = 3600.0
_PROVIDER_HISTORY_SEARCH_LIMIT = 32
_PROVIDER_HISTORY_RETRIES = 3
_PROVIDER_HISTORY_RETRY_DELAY = 0.25
_PROVIDER_HISTORY_PACING = 0.10


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

        `/status` supplies the tx-index flag and current height. Each block-detail
        RPC method is asked once at height 1 so provider-reported pruning floors
        can be compared independently. A reported floor is then verified with a
        single point request. Only a method whose own reported floor is truly
        unavailable gets a bounded method-specific binary search. Transient or
        rate-limit style responses are retried with a short bounded backoff and
        never classified as pruning. No transaction search or full-chain scan
        occurs.
        """
        transport = getattr(self, "transport", None)
        if transport is None:
            return {"tx_index": "unknown", "lowest_available_height": None}

        cache_key = (canonical_id, "endpoint_provider_rpc_capabilities", (provider.id,))

        async def load():
            tx_index = "unknown"
            latest_height = None

            try:
                payload = await transport.get_object(provider.rpc_endpoint, "/status")
                status = _core.parse_node_status(
                    payload,
                    network_id=canonical_id,
                    expected_chain_id=self.definition.transport.chain_id,
                    source_host=self.adapter._host(provider.rpc_endpoint),
                )
                tx_index = status.tx_index
                latest_height = status.local_height
            except Exception:
                pass

            paths = {
                "block": "/block?height={height}",
                "commit": "/commit?height={height}",
                "block_results": "/block_results?height={height}",
            }

            def error_text(payload):
                if not isinstance(payload, dict):
                    return ""
                error = payload.get("error")
                if isinstance(error, dict):
                    return str(error.get("data") or error.get("message") or "")
                if "code" in payload and "result" not in payload:
                    return str(payload.get("message") or payload.get("detail") or "")
                return ""

            def valid_result(kind: str, payload, height: int):
                if not isinstance(payload, dict) or "result" not in payload:
                    return None
                result = payload.get("result")
                if result is None:
                    return False
                if not isinstance(result, dict):
                    return None
                try:
                    if kind == "block":
                        block = result.get("block")
                        header = block.get("header") if isinstance(block, dict) else None
                        return isinstance(header, dict) and int(header.get("height")) == height
                    if kind == "commit":
                        signed = result.get("signed_header")
                        header = signed.get("header") if isinstance(signed, dict) else None
                        commit = signed.get("commit") if isinstance(signed, dict) else None
                        return (isinstance(header, dict) and isinstance(commit, dict)
                                and int(header.get("height")) == height
                                and int(commit.get("height")) == height)
                    return int(result.get("height")) == height
                except (TypeError, ValueError):
                    return None

            async def request(kind: str, height: int):
                for attempt in range(_PROVIDER_HISTORY_RETRIES):
                    payload = None
                    try:
                        payload = await transport.get_object(
                            provider.rpc_endpoint,
                            paths[kind].format(height=height),
                            accept_error_payload=True,
                        )
                    except Exception:
                        pass
                    else:
                        message = error_text(payload)
                        match = _HISTORY_FLOOR.search(message)
                        floor = int(match.group(1)) if match else None
                        if message:
                            if _HISTORY_UNAVAILABLE.search(message):
                                return False, floor
                        else:
                            state = valid_result(kind, payload, height)
                            if state is not None:
                                return state, floor

                    if attempt + 1 < _PROVIDER_HISTORY_RETRIES:
                        await asyncio.sleep(_PROVIDER_HISTORY_RETRY_DELAY * (attempt + 1))

                return None, None

            async def method_floor(kind: str):
                state_at_one, reported = await request(kind, 1)
                if state_at_one is True:
                    hint = 1
                elif isinstance(reported, int) and reported > 0:
                    hint = reported
                else:
                    return None

                if latest_height is None or latest_height <= 0:
                    return None
                hint = min(hint, latest_height)

                state, _reported = await request(kind, hint)
                if state is True:
                    return hint
                if state is None:
                    return None

                upper = latest_height - 1 if latest_height > hint else latest_height
                if upper <= hint:
                    return None
                upper_state, _reported = await request(kind, upper)
                if upper_state is not True:
                    return None

                unavailable = hint
                available = upper
                for _ in range(_PROVIDER_HISTORY_SEARCH_LIMIT):
                    if available - unavailable <= 1:
                        break
                    await asyncio.sleep(_PROVIDER_HISTORY_PACING)
                    middle = (unavailable + available) // 2
                    middle_state, _reported = await request(kind, middle)
                    if middle_state is None:
                        return None
                    if middle_state:
                        available = middle
                    else:
                        unavailable = middle
                return available

            lowest_available_height = None
            if latest_height is not None and latest_height > 0:
                floors = await asyncio.gather(*(method_floor(kind) for kind in paths))
                if all(isinstance(value, int) and value > 0 for value in floors):
                    lowest_available_height = max(floors)

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
        # keeps many viewers from multiplying the same provider health probe.
        # Slow-changing tx-index/usable-history capabilities have their own
        # one-hour cache and never perform transaction searches or range scans.
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
