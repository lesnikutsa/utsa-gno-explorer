"""Declarative immutable registry for server-side Cosmos networks."""

from dataclasses import dataclass
from types import MappingProxyType

from .config import CosmosNetworkConfig
from .errors import InvalidConfiguration


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

    def __post_init__(self):
        if self.family != "cosmos" or self.transport.network_id == "":
            raise InvalidConfiguration("invalid Cosmos network definition")
        if type(self.coin_type) is not int or self.coin_type < 0:
            raise InvalidConfiguration("invalid coin type")
        if len(self.assets) < 1 or len({asset.base for asset in self.assets}) != len(self.assets):
            raise InvalidConfiguration("invalid native assets")


ATOMONE = NetworkDefinition(
    transport=CosmosNetworkConfig(
        network_id="atomone-mainnet", chain_id="atomone-1",
        rpc_endpoints=("https://m-atomone.rpc.utsa.tech",),
        rest_endpoints=("https://m-atomone.api.utsa.tech",),
        request_timeout=5.0, probe_ttl=2.0, cache_ttl=2.0,
    ),
    family="cosmos", display_name="AtomOne", network_name="Mainnet",
    account_prefix="atone", validator_operator_prefix="atonevaloper",
    validator_consensus_prefix="atonevalcons", coin_type=118,
    assets=(AssetConfig("uatone", "atone", "ATONE", 6),
            AssetConfig("uphoton", "photon", "PHOTON", 6)),
    coingecko_id="atomone",
)

NETWORKS = MappingProxyType({ATOMONE.transport.network_id: ATOMONE})


def get_network(network_id: str) -> NetworkDefinition | None:
    return NETWORKS.get(network_id)
