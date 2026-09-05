"""Public Cosmos service facade with transaction-specific endpoint policy."""

from . import service_core as _core
from .service_core import *  # noqa: F401,F403
from .transaction_endpoint_policy import TransactionEndpointPolicyMixin


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


def __getattr__(name):
    """Preserve imports of existing private helpers used by focused tests."""
    return getattr(_core, name)
