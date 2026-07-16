"""Response schemas for the read-only API."""

from pydantic import BaseModel, Field


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


class BlockCommitSummary(BaseModel):
    validators: int
    signed: int
    missed: int
    nil: int
    absent: int
    invalid: int
    unknown: int


class BlockTransactionSummary(BaseModel):
    index: int
    raw_base64: str
    raw_base64_length: int
    decoded_byte_length: int | None
    decode_status: str


class BlockDetailResponse(BaseModel):
    height: int
    block_hash: str
    block_hash_base64: str
    time: str
    proposer_address: str | None
    tx_count: int
    commit: BlockCommitSummary
    transactions: list[BlockTransactionSummary]


class BlocksPagination(BaseModel):
    limit: int
    next_before_height: int | None


class BlocksResponse(BaseModel):
    items: list[BlockSummary]
    pagination: BlocksPagination


class ValidatorUptime(BaseModel):
    network_blocks: int = Field(ge=0)
    active_blocks: int = Field(ge=0)
    signed_blocks: int = Field(ge=0)
    nil_blocks: int = Field(ge=0)
    absent_blocks: int = Field(ge=0)
    invalid_blocks: int = Field(ge=0)
    unknown_blocks: int = Field(ge=0)
    uptime_percent: float


class ValidatorListItem(BaseModel):
    address: str
    public_key_type: str | None
    voting_power: str
    percent: float
    proposer_priority: str | None
    uptime_20: ValidatorUptime
    uptime_100: ValidatorUptime


class ValidatorsResponse(BaseModel):
    height: int
    total: int
    total_voting_power: str
    items: list[ValidatorListItem]
