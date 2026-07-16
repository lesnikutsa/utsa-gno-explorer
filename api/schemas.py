"""Response schemas for the read-only API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    chain_id: str
    indexed_height: int
    finalized_tip_height: int | None
    indexer_lag: int | None
    rpc_last_checked_at: str | None
    api_version: str


class BlockSummary(BaseModel):
    height: int
    block_hash: str
    time: str
    proposer_address: str | None
    tx_count: int


class NetworkValidators(BaseModel):
    height: int
    active_count: int
    total_voting_power: str


class SelectedRpc(BaseModel):
    url: str
    healthy: bool | None
    catching_up: bool | None
    observed_height: int | None
    lag: int | None
    last_checked_at: str | None


class NetworkResponse(BaseModel):
    chain_id: str
    rpc_height: int | None
    finalized_tip_height: int | None
    indexed_height: int
    indexer_lag: int | None
    latest_block: BlockSummary
    validators: NetworkValidators
    selected_rpc: SelectedRpc | None


class BlocksPagination(BaseModel):
    limit: int
    next_before_height: int | None


class BlocksResponse(BaseModel):
    items: list[BlockSummary]
    pagination: BlocksPagination
