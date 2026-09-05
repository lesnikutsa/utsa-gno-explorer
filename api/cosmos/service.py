"""Public Cosmos service facade with transaction-specific endpoint policy."""

from . import service_core as _core
from .service_core import *  # noqa: F401,F403
from .transaction_endpoint_policy import TransactionEndpointPolicyMixin


class CosmosService(TransactionEndpointPolicyMixin, _core.CosmosService):
    """Cosmos aggregation service with operation-aware transaction failover."""


def __getattr__(name):
    """Preserve imports of existing private helpers used by focused tests."""
    return getattr(_core, name)
