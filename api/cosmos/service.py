"""Public Cosmos service facade with transaction-specific endpoint policy."""

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
