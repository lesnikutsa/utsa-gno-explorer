"""Validated declarative registry for request-driven Cosmos networks."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from .config import CosmosNetworkConfig
from .errors import InvalidConfiguration

NETWORKS_ROOT = Path(__file__).resolve().parents[2] / "networks"
PUBLIC_CAPABILITIES = frozenset({"overview", "blocks", "transactions", "network-parameters"})
_PREFIX = re.compile(r"^[a-z][a-z0-9]{1,63}$")
_EXPECTED_KEYS = frozenset({
    "id", "family", "chain_id", "display_name", "network_name", "rpc_endpoints",
    "rest_endpoints", "account_prefix", "validator_operator_prefix",
    "validator_consensus_prefix", "coin_type", "assets", "coingecko_id",
    "logo_url", "capabilities",
})


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


def load_network_file(path: Path) -> NetworkDefinition:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidConfiguration("invalid network configuration file") from exc
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
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
    return NetworkDefinition(
        transport=CosmosNetworkConfig(
            network_id=_text(payload["id"], "network ID", 64),
            chain_id=_text(payload["chain_id"], "chain ID"),
            rpc_endpoints=payload["rpc_endpoints"], rest_endpoints=payload["rest_endpoints"],
            request_timeout=5.0, probe_ttl=2.0, cache_ttl=2.0),
        family=_text(payload["family"], "family"),
        display_name=_text(payload["display_name"], "display name", 64),
        network_name=_text(payload["network_name"], "network name", 64),
        account_prefix=payload["account_prefix"],
        validator_operator_prefix=payload["validator_operator_prefix"],
        validator_consensus_prefix=payload["validator_consensus_prefix"],
        coin_type=payload["coin_type"], assets=parsed_assets,
        coingecko_id=_text(payload["coingecko_id"], "CoinGecko ID", 128),
        logo_url=payload["logo_url"], capabilities=capabilities)


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


NETWORKS = load_networks()
ATOMONE = NETWORKS["atomone-mainnet"]


def get_network(network_id: str) -> NetworkDefinition | None:
    return NETWORKS.get(network_id)


def public_networks():
    return [definition.public() for definition in NETWORKS.values()]
