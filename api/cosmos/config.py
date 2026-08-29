"""Immutable server-side Cosmos network configuration."""

from dataclasses import dataclass
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .errors import InvalidConfiguration

MAX_ENDPOINTS = 16
MAX_URL_LENGTH = 2048
MAX_CHAIN_ID_LENGTH = 128
MAX_TIMEOUT_SECONDS = 30.0
MAX_HEIGHT_LAG = 10_000
MAX_TTL_SECONDS = 300.0
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _endpoint(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_URL_LENGTH:
        raise InvalidConfiguration("invalid endpoint URL")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise InvalidConfiguration("invalid endpoint URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidConfiguration("invalid endpoint URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.path not in {"", "/"}
        or parsed.netloc.endswith(":")
    ):
        raise InvalidConfiguration("invalid endpoint URL")
    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        dns_name = hostname[:-1] if hostname.endswith(".") else hostname
        labels = dns_name.split(".")
        if (
            not dns_name
            or len(dns_name) > 253
            or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                   for label in labels)
        ):
            raise InvalidConfiguration("invalid endpoint URL")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname.lower()
    return urlunsplit((parsed.scheme, f"{host}:{port}" if port is not None else host, "", "", ""))


def _endpoints(values: object, kind: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_ENDPOINTS:
        raise InvalidConfiguration(f"{kind} endpoints must contain 1 to {MAX_ENDPOINTS} entries")
    return tuple(dict.fromkeys(_endpoint(value) for value in values))


@dataclass(frozen=True)
class CosmosNetworkConfig:
    network_id: str
    chain_id: str
    rpc_endpoints: tuple[str, ...]
    rest_endpoints: tuple[str, ...]
    request_timeout: float = 10.0
    max_height_lag: int = 10
    probe_ttl: float = 15.0
    cache_ttl: float = 10.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if not isinstance(self.network_id, str) or len(self.network_id) > 64 or not _SLUG.fullmatch(self.network_id):
            raise InvalidConfiguration("network ID must be a safe URL slug")
        if (
            not isinstance(self.chain_id, str)
            or not 1 <= len(self.chain_id) <= MAX_CHAIN_ID_LENGTH
            or self.chain_id != self.chain_id.strip()
            or any(unicodedata.category(char).startswith("C") for char in self.chain_id)
        ):
            raise InvalidConfiguration("runtime chain ID is invalid")
        if type(self.request_timeout) not in {int, float} or not 0.1 <= self.request_timeout <= MAX_TIMEOUT_SECONDS:
            raise InvalidConfiguration("request timeout is out of bounds")
        if type(self.max_height_lag) is not int or not 0 <= self.max_height_lag <= MAX_HEIGHT_LAG:
            raise InvalidConfiguration("maximum height lag is out of bounds")
        for name, value in (("probe TTL", self.probe_ttl), ("cache TTL", self.cache_ttl)):
            if type(value) not in {int, float} or not 0 <= value <= MAX_TTL_SECONDS:
                raise InvalidConfiguration(f"{name} is out of bounds")
        if type(self.max_response_bytes) is not int or not 1024 <= self.max_response_bytes <= 10_000_000:
            raise InvalidConfiguration("maximum response size is out of bounds")
        object.__setattr__(self, "rpc_endpoints", _endpoints(self.rpc_endpoints, "RPC"))
        object.__setattr__(self, "rest_endpoints", _endpoints(self.rest_endpoints, "REST"))
