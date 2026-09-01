"""Bounded, secret-free Cosmos adapter errors."""


class CosmosAdapterError(RuntimeError):
    """Base error whose message is safe to expose to internal callers."""


class InvalidConfiguration(CosmosAdapterError):
    """Operator-provided network configuration is invalid."""


class RejectedEndpoint(CosmosAdapterError):
    """An endpoint failed identity or freshness validation."""


class MalformedUpstreamResponse(CosmosAdapterError):
    """An upstream response did not match the bounded expected shape."""


class AllEndpointsUnavailable(CosmosAdapterError):
    """No validated endpoint completed an operation."""


class TransactionNotFound(CosmosAdapterError):
    """Every conclusive transaction lookup reported an unknown hash."""


class ValidatorNotFound(CosmosAdapterError):
    """The requested validator is not present in the staking validator set."""


class InvalidValidatorAddress(CosmosAdapterError):
    """The requested operator address is malformed or uses another prefix."""


class HistoryUnavailable(CosmosAdapterError):
    """A requested block is outside the connected RPC's retained history."""

    reason = "history_unavailable"

    def __init__(self, requested_height: int, lowest_available_height: int | None = None):
        super().__init__(self.reason)
        self.requested_height = requested_height
        self.lowest_available_height = lowest_available_height


class NodeNotSynced(CosmosAdapterError):
    """A requested height is ahead of the syncing RPC's local head."""

    reason = "node_not_synced"
