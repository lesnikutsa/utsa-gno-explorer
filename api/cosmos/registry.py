"""Validated declarative registry for request-driven Cosmos networks."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from .config import CosmosNetworkConfig
from .errors import InvalidConfiguration

NETWORKS_ROOT = Path(__file__).resolve().parents[2] / "networks"
PUBLIC_CAPABILITIES = frozenset({"overview", "blocks", "transactions", "validators", "network-parameters"})
_PREFIX = re.compile(r"^[a-z][a-z0-9]{1,63}$")
_PROVIDER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIRED_KEYS = frozenset({
    "id", "family", "chain_id", "display_name", "network_name", "rpc_endpoints",
    "rest_endpoints", "account_prefix", "validator_operator_prefix",
    "validator_consensus_prefix", "coin_type", "assets", "coingecko_id",
    "logo_url", "capabilities",
})
_OPTIONAL_KEYS = frozenset({"endpoint_providers"})


@dataclass(frozen=True)
class AssetConfig:
    base: str
    display: str
    symbol: str
    exponent: int

    def __post_init__(self):
        if not all(isinstance(value, str) and value.isascii() and value.isalnum()
                   for value in (self.base, self.display, self.symbol)):
            raise InvalidConfiguration("invalid asset metadata")
        if type(self.exponent) is not int or not 0 <= self.exponent <= 18:
            raise InvalidConfiguration("invalid asset exponent")

    def public(self):
        return {"base": self.base, "display": self.display, "symbol": self.symbol,
                "exponent": self.exponent}


@dataclass(frozen=True)
class EndpointProvider:
    id: str
    label: str
    rpc_endpoint: str
    rest_endpoint: str

    def __post_init__(self):
        if not isinstance(self.id, str) or len(self.id) > 32 or _PROVIDER_ID.fullmatch(self.id) is None:
            raise InvalidConfiguration("invalid endpoint provider ID")
        if (not isinstance(self.label, str) or not 1 <= len(self.label) <= 64
                or self.label != self.label.strip()):
            raise InvalidConfiguration("invalid endpoint provider label")


@dataclass(frozen=True)
class NetworkDefinition:
    transport: CosmosNetworkConfig
    family: str
    display_name: str
    network_name: str
    account_prefix: str
    validator_operator_prefix: str
    validator_consensus_prefix: str
    coin_type: int
    assets: tuple[AssetConfig, ...]
    coingecko_id: str
    logo_url: str = "https://example.invalid/logo.png"
    capabilities: tuple[str, ...] = ("overview", "blocks")
    endpoint_providers: tuple[EndpointProvider, ...] = ()
    canonical_id: str | None = None
    selected_provider_id: str | None = None

    def __post_init__(self):
        if self.family != "cosmos" or self.transport.network_id == "":
            raise InvalidConfiguration("invalid Cosmos network definition")
        if type(self.coin_type) is not int or self.coin_type < 0:
            raise InvalidConfiguration("invalid coin type")
        if len(self.assets) < 1 or len({asset.base for asset in self.assets}) != len(self.assets):
            raise InvalidConfiguration("invalid native assets")
        for prefix in (self.account_prefix, self.validator_operator_prefix,
                       self.validator_consensus_prefix):
            if not isinstance(prefix, str) or _PREFIX.fullmatch(prefix) is None:
                raise InvalidConfiguration("invalid address prefix")
        parsed_logo = urlsplit(self.logo_url)
        if (parsed_logo.scheme != "https" or not parsed_logo.hostname
                or parsed_logo.username or parsed_logo.password):
            raise InvalidConfiguration("invalid public logo URL")
        if (not isinstance(self.capabilities, tuple) or not self.capabilities
                or len(set(self.capabilities)) != len(self.capabilities)
                or any(item not in PUBLIC_CAPABILITIES for item in self.capabilities)):
            raise InvalidConfiguration("invalid Cosmos capabilities")
        provider_ids = [provider.id for provider in self.endpoint_providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise InvalidConfiguration("duplicate endpoint provider ID")
        if self.endpoint_providers:
            if len(self.endpoint_providers) != len(self.transport.rpc_endpoints):
                raise InvalidConfiguration("endpoint providers must match RPC endpoints")
            if len(self.endpoint_providers) != len(self.transport.rest_endpoints):
                raise InvalidConfiguration("endpoint providers must match REST endpoints")
            if tuple(provider.rpc_endpoint for provider in self.endpoint_providers) != self.transport.rpc_endpoints:
                raise InvalidConfiguration("endpoint provider RPC order mismatch")
            if tuple(provider.rest_endpoint for provider in self.endpoint_providers) != self.transport.rest_endpoints:
                raise InvalidConfiguration("endpoint provider REST order mismatch")
        if self.canonical_id is not None and (
                not isinstance(self.canonical_id, str) or len(self.canonical_id) > 64
                or _PROVIDER_ID.fullmatch(self.canonical_id) is None):
            raise InvalidConfiguration("invalid canonical network ID")
        if self.selected_provider_id is not None and self.selected_provider_id not in provider_ids:
            raise InvalidConfiguration("invalid selected endpoint provider")

    def public(self):
        return {
            "id": self.transport.network_id, "family": self.family,
            "chain_id": self.transport.chain_id, "display_name": self.display_name,
            "network_name": self.network_name, "logo_url": self.logo_url,
            "assets": [asset.public() for asset in self.assets],
            "address_prefixes": {"account": self.account_prefix,
                "validator_operator": self.validator_operator_prefix,
                "validator_consensus": self.validator_consensus_prefix},
            "capabilities": list(self.capabilities),
        }


def _text(value, name, maximum=128):
    if not isinstance(value, str) or not value or len(value) > maximum or value != value.strip():
        raise InvalidConfiguration(f"invalid {name}")
    return value


def provider_alias_id(network_id: str, provider_id: str) -> str:
    alias = f"{network_id}-provider-{provider_id}"
    if len(alias) > 64 or _PROVIDER_ID.fullmatch(alias) is None:
        raise InvalidConfiguration("invalid endpoint provider alias")
    return alias


def load_network_file(path: Path) -> NetworkDefinition:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidConfiguration("invalid network configuration file") from exc
    keys = set(payload) if isinstance(payload, dict) else set()
    if (not isinstance(payload, dict) or not _REQUIRED_KEYS.issubset(keys)
            or not keys.issubset(_REQUIRED_KEYS | _OPTIONAL_KEYS)):
        raise InvalidConfiguration("invalid network configuration fields")
    assets = payload["assets"]
    if not isinstance(assets, list) or not assets or len(assets) > 16:
        raise InvalidConfiguration("invalid native assets")
    try:
        parsed_assets = tuple(AssetConfig(**asset) for asset in assets
                              if isinstance(asset, dict) and set(asset) == {"base", "display", "symbol", "exponent"})
        capabilities = tuple(payload["capabilities"])
    except (TypeError, KeyError):
        raise InvalidConfiguration("invalid network configuration values") from None
    if len(parsed_assets) != len(assets):
        raise InvalidConfiguration("invalid asset fields")

    transport = CosmosNetworkConfig(
        network_id=_text(payload["id"], "network ID", 64),
        chain_id=_text(payload["chain_id"], "chain ID"),
        rpc_endpoints=payload["rpc_endpoints"], rest_endpoints=payload["rest_endpoints"],
        request_timeout=5.0, probe_ttl=2.0, cache_ttl=2.0)

    provider_rows = payload.get("endpoint_providers", [])
    if not isinstance(provider_rows, list):
        raise InvalidConfiguration("invalid endpoint providers")
    if provider_rows and len(provider_rows) != len(transport.rpc_endpoints):
        raise InvalidConfiguration("endpoint providers must match configured pairs")
    parsed_providers = []
    for index, row in enumerate(provider_rows):
        if not isinstance(row, dict) or set(row) != {"id", "label"}:
            raise InvalidConfiguration("invalid endpoint provider fields")
        parsed_providers.append(EndpointProvider(
            id=_text(row["id"], "endpoint provider ID", 32),
            label=_text(row["label"], "endpoint provider label", 64),
            rpc_endpoint=transport.rpc_endpoints[index],
            rest_endpoint=transport.rest_endpoints[index],
        ))

    return NetworkDefinition(
        transport=transport,
        family=_text(payload["family"], "family"),
        display_name=_text(payload["display_name"], "display name", 64),
        network_name=_text(payload["network_name"], "network name", 64),
        account_prefix=payload["account_prefix"],
        validator_operator_prefix=payload["validator_operator_prefix"],
        validator_consensus_prefix=payload["validator_consensus_prefix"],
        coin_type=payload["coin_type"], assets=parsed_assets,
        coingecko_id=_text(payload["coingecko_id"], "CoinGecko ID", 128),
        logo_url=payload["logo_url"], capabilities=capabilities,
        endpoint_providers=tuple(parsed_providers))


def load_networks(root: Path = NETWORKS_ROOT):
    definitions = {}
    for path in sorted(root.glob("*/network.json")):
        definition = load_network_file(path)
        if path.parent.name != definition.transport.network_id or definition.transport.network_id in definitions:
            raise InvalidConfiguration("network directory and ID must match uniquely")
        definitions[definition.transport.network_id] = definition
    if not definitions:
        raise InvalidConfiguration("no Cosmos network configurations found")
    return MappingProxyType(definitions)


def _expand_provider_aliases(canonical_networks):
    expanded = dict(canonical_networks)
    for canonical_id, definition in canonical_networks.items():
        for provider in definition.endpoint_providers:
            alias_id = provider_alias_id(canonical_id, provider.id)
            if alias_id in expanded:
                raise InvalidConfiguration("duplicate endpoint provider alias")
            transport = CosmosNetworkConfig(
                network_id=alias_id,
                chain_id=definition.transport.chain_id,
                rpc_endpoints=(provider.rpc_endpoint,),
                rest_endpoints=(provider.rest_endpoint,),
                request_timeout=definition.transport.request_timeout,
                max_height_lag=definition.transport.max_height_lag,
                probe_ttl=definition.transport.probe_ttl,
                cache_ttl=definition.transport.cache_ttl,
                max_response_bytes=definition.transport.max_response_bytes,
            )
            expanded[alias_id] = replace(
                definition,
                transport=transport,
                endpoint_providers=(EndpointProvider(
                    id=provider.id,
                    label=provider.label,
                    rpc_endpoint=provider.rpc_endpoint,
                    rest_endpoint=provider.rest_endpoint,
                ),),
                canonical_id=canonical_id,
                selected_provider_id=provider.id,
            )
    return MappingProxyType(expanded)


CANONICAL_NETWORKS = load_networks()
NETWORKS = _expand_provider_aliases(CANONICAL_NETWORKS)
ATOMONE = NETWORKS["atomone-mainnet"]


def get_network(network_id: str) -> NetworkDefinition | None:
    return NETWORKS.get(network_id)


def public_networks():
    return [definition.public() for definition in CANONICAL_NETWORKS.values()]
