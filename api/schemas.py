"""Response schemas for the read-only API."""

from typing import Literal

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
    proposer_moniker: str | None = None
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
    tx_hash: str | None = None
    raw_base64: str
    raw_base64_length: int
    decoded_byte_length: int | None
    decode_status: str


class TransactionDetailResponse(BaseModel):
    block_height: int = Field(ge=1)
    block_hash: str
    block_time: str
    proposer_address: str | None
    proposer_moniker: str | None = None
    index: int = Field(ge=0)
    tx_hash: str | None = None
    raw_base64: str
    raw_base64_length: int = Field(ge=0)
    decoded_byte_length: int | None = Field(default=None, ge=0)
    decode_status: str


class BlockDetailResponse(BaseModel):
    height: int
    block_hash: str
    block_hash_base64: str
    time: str
    proposer_address: str | None
    proposer_moniker: str | None = None
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


ValoperServerType = Literal["cloud", "on-prem", "data-center"]


class ValidatorListItem(BaseModel):
    address: str
    public_key_type: str | None
    voting_power: str
    percent: float
    proposer_priority: str | None
    moniker: str | None = None
    operator_address: str | None = None
    server_type: ValoperServerType | None = None
    valoper_source_height: int | None = Field(default=None, ge=1)
    uptime_20: ValidatorUptime
    uptime_100: ValidatorUptime


class ValidatorsResponse(BaseModel):
    height: int
    total: int
    total_voting_power: str
    items: list[ValidatorListItem]


class ValidatorSearchItem(BaseModel):
    address: str
    moniker: str | None = None
    operator_address: str | None = None


class ValidatorSearchResponse(BaseModel):
    items: list[ValidatorSearchItem]


class ValidatorCurrentStatus(BaseModel):
    active: bool
    height: int = Field(ge=0)
    voting_power: str | None
    voting_power_percent: float
    proposer_priority: str | None


class ValidatorSigningHistoryItem(BaseModel):
    height: int = Field(ge=0)
    time: str
    status: Literal["commit", "nil", "absent", "invalid", "not_active", "unknown"]


class ValidatorSigningHistory(BaseModel):
    network_blocks: int = Field(ge=0)
    start_height: int | None = Field(default=None, ge=0)
    end_height: int | None = Field(default=None, ge=0)
    items: list[ValidatorSigningHistoryItem]


ValidatorSigningStatus = Literal["commit", "nil", "absent", "invalid", "not_active", "unknown"]


class ValidatorSigningHistoryBlock(BaseModel):
    height: int = Field(ge=0)
    time: str


class ValidatorSigningHistoryBatchItem(BaseModel):
    address: str
    statuses: list[ValidatorSigningStatus]


class ValidatorSigningHistoryBatchResponse(BaseModel):
    height: int = Field(ge=0)
    network_blocks: int = Field(ge=0)
    start_height: int | None = Field(default=None, ge=0)
    end_height: int | None = Field(default=None, ge=0)
    blocks: list[ValidatorSigningHistoryBlock]
    items: list[ValidatorSigningHistoryBatchItem]


class ValidatorDetailResponse(BaseModel):
    address: str
    public_key_type: str | None
    public_key_value: str
    first_seen_height: int = Field(ge=0)
    last_seen_height: int = Field(ge=0)
    moniker: str | None = None
    operator_address: str | None = None
    signing_pubkey: str | None = None
    description: str | None = None
    server_type: ValoperServerType | None = None
    valoper_source_height: int | None = Field(default=None, ge=1)
    current: ValidatorCurrentStatus
    uptime_20: ValidatorUptime
    uptime_100: ValidatorUptime
    signing_history: ValidatorSigningHistory
