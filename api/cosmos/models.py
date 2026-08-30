"""Minimal normalized Cosmos models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainHead:
    network_id: str
    chain_id: str
    latest_height: int
    latest_block_time: str
    catching_up: bool
    source_host: str


@dataclass(frozen=True)
class BlockSummary:
    network_id: str
    chain_id: str
    height: int
    block_hash: str
    block_time: str
    proposer_address: str
    transaction_count: int


@dataclass(frozen=True)
class NodeStatus:
    network_id: str
    chain_id: str
    local_height: int
    latest_block_time: str
    catching_up: bool
    tx_index: str
    node_version: str | None
    application_name: str | None
    application_version: str | None
    sdk_version: str | None
    cometbft_version: str | None
    source_host: str
