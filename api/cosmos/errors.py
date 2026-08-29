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
