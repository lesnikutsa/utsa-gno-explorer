"""Response schemas for the read-only API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


JsonSafeScalar = str | int | float | bool | None


class AccountBalance(BaseModel):
    denom: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=256, pattern=r"^(0|[1-9][0-9]*)$")
    display_amount: str = Field(min_length=1, max_length=264)
    symbol: str = Field(min_length=1, max_length=128)
    decimals: int = Field(ge=0, le=30)


class AccountPublicKey(BaseModel):
    type: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)


class AccountValidatorRelation(BaseModel):
    moniker: str = Field(min_length=1, max_length=256)
    operator_address: str = Field(min_length=1, max_length=90)
    signing_address: str = Field(min_length=1, max_length=128)


class AccountSource(BaseModel):
    kind: Literal["rpc"]
    chain_id: str = Field(min_length=1, max_length=128)
    rpc_url: str = Field(min_length=1, max_length=2048)


class AccountResponse(BaseModel):
    address: str = Field(min_length=1, max_length=90)
    found: bool
    balances: list[AccountBalance] = Field(max_length=64)
    account_number: str | None = Field(default=None, max_length=40, pattern=r"^(0|[1-9][0-9]*)$")
    sequence: str | None = Field(default=None, max_length=40, pattern=r"^(0|[1-9][0-9]*)$")
    public_key: AccountPublicKey | None
    validator_relation: AccountValidatorRelation | None
    source: AccountSource
    observed_height: int = Field(gt=0)


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
    latency_ms: int | None = Field(default=None, ge=0, le=30000)


class RpcPoolEndpoint(BaseModel):
    model_config = ConfigDict(strict=True)
    url: str = Field(min_length=1, max_length=2048)
    selected: bool
    state: Literal["healthy", "catching_up", "stale", "wrong_chain", "unavailable", "unknown"]
    latency_ms: int | None = Field(default=None, ge=0, le=30000)
    lag: int | None = Field(default=None, ge=0)
    last_checked_at: str | None


class RpcPool(BaseModel):
    model_config = ConfigDict(strict=True)
    total: int = Field(ge=0, le=32)
    available: int = Field(ge=0, le=32)
    last_checked_at: str | None
    endpoints: list[RpcPoolEndpoint] = Field(max_length=32)

    @model_validator(mode="after")
    def available_not_above_total(self):
        if self.available > self.total:
            raise ValueError("available must not exceed total")
        if len(self.endpoints) != self.total:
            raise ValueError("total must match endpoints")
        return self


class NetworkResponse(BaseModel):
    chain_id: str
    rpc_height: int | None
    finalized_tip_height: int | None
    indexed_height: int
    indexer_lag: int | None
    average_block_time_seconds: float | None = Field(default=None, ge=0)
    average_block_time_sample_size: int = Field(ge=0)
    latest_block: BlockSummary
    validators: NetworkValidators
    selected_rpc: SelectedRpc | None
    rpc_pool: RpcPool


class NetworkDistributionRpcSources(BaseModel):
    total: int = Field(ge=0)
    ok: int = Field(ge=0)


class NetworkDistributionRegion(BaseModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class NetworkDistributionCountry(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str = Field(min_length=1)
    count: int = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class NetworkDistributionProvider(BaseModel):
    asn: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1)
    count: int = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class NetworkDistributionResponse(BaseModel):
    chain_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    updated_at: str
    rpc_sources: NetworkDistributionRpcSources
    visible_node_ids: int = Field(ge=0)
    unique_public_ips: int = Field(ge=0)
    geolocated_node_ids: int = Field(ge=0)
    geolocated_public_ips: int = Field(ge=0)
    geolocation_coverage_percent: float = Field(ge=0, le=100)
    node_id_ip_conflicts: int = Field(ge=0)
    region_count: int = Field(ge=0)
    country_count: int = Field(ge=0)
    provider_count: int = Field(ge=0)
    region_covered_public_ips: int = Field(ge=0)
    country_covered_public_ips: int = Field(ge=0)
    provider_covered_public_ips: int = Field(ge=0)
    region_coverage_percent: float = Field(ge=0, le=100)
    country_coverage_percent: float = Field(ge=0, le=100)
    provider_coverage_percent: float = Field(ge=0, le=100)
    regions: list[NetworkDistributionRegion]
    countries: list[NetworkDistributionCountry]
    providers: list[NetworkDistributionProvider]


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
    execution_status: Literal["success", "failed"] | None = None
    gas_wanted: str | None = None
    gas_used: str | None = None
    error: str | None = None
    log: str | None = None
    info: str | None = None


class TransactionSummaryPrimary(BaseModel):
    type: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)


class TransactionSummaryMessage(TransactionSummaryPrimary):
    sender: JsonSafeScalar = None
    recipient: JsonSafeScalar = None
    amount: JsonSafeScalar = None
    send: JsonSafeScalar = None
    package_path: JsonSafeScalar = None
    package_name: JsonSafeScalar = None
    function: JsonSafeScalar = None
    args_count: JsonSafeScalar = None
    file_count: JsonSafeScalar = None
    expires_at: JsonSafeScalar = None
    allow_paths_count: JsonSafeScalar = None
    spend_limit: JsonSafeScalar = None
    spend_period: JsonSafeScalar = None


class TransactionSummaryResponse(BaseModel):
    schema_version: Literal[1]
    chain_family: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    parse_status: Literal["unparsed", "parsed", "unsupported", "invalid"]
    message_count: int | None = Field(default=None, ge=0, le=100000)
    messages_truncated: bool
    primary: TransactionSummaryPrimary
    messages: list[TransactionSummaryMessage] = Field(max_length=20)


class TransactionMessageArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_index: int = Field(ge=0)
    values: list[str] = Field(max_length=16)
    truncated: bool

    @model_validator(mode="after")
    def validate_values(self):
        if any(len(value) > 256 or (value != "" and not value.isprintable()) for value in self.values):
            raise ValueError("argument values must be bounded printable strings")
        return self


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
    summary: TransactionSummaryResponse | None = None
    message_arguments: list[TransactionMessageArguments] | None = Field(default=None, max_length=20)
    execution_status: Literal["success", "failed"] | None = None
    gas_wanted: str | None = None
    gas_used: str | None = None
    error: str | None = None
    log: str | None = None
    info: str | None = None

    @model_validator(mode="after")
    def validate_message_argument_order(self):
        if self.message_arguments is not None:
            indexes = [entry.message_index for entry in self.message_arguments]
            if indexes != sorted(set(indexes)):
                raise ValueError("message argument indexes must be unique and sorted")
        return self


class TransactionHashLookupResponse(BaseModel):
    block_height: int = Field(ge=1)
    index: int = Field(ge=0)
    tx_hash: str = Field(pattern=r"^[0-9A-F]{64}$")


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


class TransactionListItem(BaseModel):
    block_height: int = Field(ge=1)
    index: int = Field(ge=0)
    tx_hash: str | None = None
    block_time: str
    type: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=80)
    execution_status: Literal["success", "failed"] | None = None
    gas_wanted: str | None = None
    gas_used: str | None = None
    error: str | None = None
    log: str | None = None
    info: str | None = None


class TransactionsPagination(BaseModel):
    limit: int
    next_before_height: int | None
    next_before_tx_index: int | None


class TransactionsResponse(BaseModel):
    items: list[TransactionListItem]
    pagination: TransactionsPagination


class AccountTransactionListItem(TransactionListItem):
    direction: Literal["outgoing", "incoming", "self"]
    counterparty: str | None = Field(default=None, min_length=8, max_length=90)
    amount: str | int | float | None = None


class AccountTransactionsPagination(TransactionsPagination):
    pass


class AccountTransactionsResponse(BaseModel):
    items: list[AccountTransactionListItem]
    pagination: AccountTransactionsPagination


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
    uptime_1000: ValidatorUptime


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
    uptime_1000: ValidatorUptime
    signing_history: ValidatorSigningHistory


GovernanceStatus = Literal["ACTIVE", "ACCEPTED", "REJECTED", "UNKNOWN"]
GovernanceVoteOption = Literal["YES", "NO", "ABSTAIN"]
GovernanceParseStatus = Literal["parsed", "partial", "empty"]


class GovernanceSourceResponse(BaseModel):
    chain_id: str = Field(min_length=1, max_length=128)
    realm_path: str = Field(min_length=1, max_length=512)
    source_height: int = Field(ge=1)
    page_count: int = Field(ge=1, le=100)
    proposal_count: int = Field(ge=0, le=1000)
    first_proposal_id: int | None = Field(default=None, ge=0)
    latest_proposal_id: int | None = Field(default=None, ge=0)
    last_success_at: str


class GovernanceStatusCounts(BaseModel):
    active: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    unknown: int = Field(ge=0)


class GovernanceProposalListItem(BaseModel):
    proposal_id: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=1000)
    author_display: str | None = Field(default=None, max_length=1000)
    author_address: str | None = Field(default=None, pattern=r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")
    status: GovernanceStatus
    eligible_tiers: list[str]
    yes_percent: float | None = Field(default=None, ge=0, le=100)
    no_percent: float | None = Field(default=None, ge=0, le=100)
    abstain_percent: float | None = Field(default=None, ge=0, le=100)
    voter_count: int = Field(ge=0, le=1000)


class GovernanceProposalsPagination(BaseModel):
    limit: int = Field(ge=1, le=100)
    next_before_proposal_id: int | None = Field(default=None, ge=0)


class GovernanceProposalsResponse(BaseModel):
    source: GovernanceSourceResponse
    status_counts: GovernanceStatusCounts
    items: list[GovernanceProposalListItem]
    pagination: GovernanceProposalsPagination


class GovernanceVoteResponse(BaseModel):
    voter_display: str = Field(min_length=1, max_length=1000)
    voter_address: str | None = Field(default=None, pattern=r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")
    option: GovernanceVoteOption
    tier: str = Field(min_length=1, max_length=64)
    voting_power: str = Field(pattern=r"^(0|[1-9][0-9]*)$")
    first_observed_height: int = Field(ge=1)
    last_observed_height: int = Field(ge=1)


class GovernanceProposalDetail(GovernanceProposalListItem):
    description: str = Field(max_length=100000)
    executor_text: str | None = Field(default=None, max_length=100000)
    executor_creation_realm: str | None = Field(default=None, max_length=1000)
    rejection_reason: str | None = Field(default=None, max_length=10000)
    detail_parse_status: Literal["parsed", "partial"]
    votes_parse_status: Literal["parsed", "empty"]
    first_observed_height: int = Field(ge=1)
    last_observed_height: int = Field(ge=1)
    first_observed_at: str
    last_observed_at: str
    votes: list[GovernanceVoteResponse]


class GovernanceProposalDetailResponse(BaseModel):
    source: GovernanceSourceResponse
    proposal: GovernanceProposalDetail

class RealmCatalogItem(BaseModel):
    path: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    kind: Literal["realm", "package"]
    rpc_visible: bool
    deployer_address: str | None
    deploy_height: int | None
    deploy_tx_index: int | None
    first_seen_height: int | None
    last_activity_height: int | None
    last_activity_tx_index: int | None
    last_activity_at: str | None
    call_count: int = Field(ge=0)
    successful_call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    unknown_result_call_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)

class RealmCatalogSummary(BaseModel):
    total_items: int = Field(ge=0)
    total_realms: int = Field(ge=0)
    total_packages: int = Field(ge=0)
    rpc_visible_items: int = Field(ge=0)
    active_24h: int = Field(ge=0)
    indexed_height: int = Field(ge=0)
    catalog_observed_height: int = Field(gt=0)
    catalog_refreshed_at: str
    activity_from_height: int | None
    activity_through_height: int | None

class RealmCatalogPagination(BaseModel):
    next_before_activity_height: int | None
    next_before_path: str | None

class RealmCatalogResponse(BaseModel):
    summary: RealmCatalogSummary
    items: list[RealmCatalogItem]
    pagination: RealmCatalogPagination

class RealmRankingSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chain_id: str = Field(min_length=1, max_length=128)
    indexed_height: int = Field(ge=0)
    catalog_observed_height: int = Field(gt=0)
    activity_from_height: int | None
    activity_through_height: int | None

class RealmTopResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: RealmRankingSource
    items: list[RealmCatalogItem] = Field(max_length=10)

class RealmApplicationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=256)
    website: str | None = Field(default=None, max_length=256)
    metadata_source: Literal["curated_registry"]

class RealmNamespaceMember(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=256)
    rpc_visible: bool
    first_seen_height: int | None = Field(default=None, gt=0)
    last_activity_height: int | None = Field(default=None, gt=0)
    last_activity_tx_index: int | None = Field(default=None, ge=0)
    last_activity_at: str | None = None
    call_count: int = Field(ge=0)
    successful_call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    unknown_result_call_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)


class RealmDetailSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chain_id: str = Field(min_length=1, max_length=128)
    indexed_height: int = Field(ge=0)
    catalog_observed_height: int = Field(gt=0)
    catalog_refreshed_at: str
    activity_from_height: int | None = Field(default=None, gt=0)
    activity_through_height: int | None = Field(default=None, gt=0)
    call_index_from_height: int | None = Field(default=None, gt=0)
    call_index_through_height: int | None = Field(default=None, gt=0)
    call_index_complete: bool

    @model_validator(mode="after")
    def validate_ranges(self) -> "RealmDetailSource":
        if (self.activity_from_height is None) != (self.activity_through_height is None):
            raise ValueError("activity range fields must be supplied together")
        if (self.call_index_from_height is None) != (self.call_index_through_height is None):
            raise ValueError("call-index range fields must be supplied together")
        if (self.activity_from_height is not None
                and self.activity_through_height < self.activity_from_height):
            raise ValueError("activity range is invalid")
        if (self.call_index_from_height is not None
                and self.call_index_through_height < self.call_index_from_height):
            raise ValueError("call-index range is invalid")
        if self.call_index_complete and self.call_index_from_height is None:
            raise ValueError("complete call-index coverage requires range fields")
        return self


class RealmDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: RealmDetailSource
    item: RealmCatalogItem
    namespace_key: str | None = Field(default=None, min_length=1, max_length=256)
    application: RealmApplicationMetadata | None


class RealmCallSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chain_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=256)
    indexed_height: int = Field(ge=0)
    from_height: int = Field(gt=0)
    through_height: int = Field(gt=0)


class RealmCallListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    block_height: int = Field(gt=0)
    tx_index: int = Field(ge=0)
    message_index: int = Field(ge=0, le=19)
    block_time: str
    tx_hash: str | None = Field(default=None, pattern=r"^[0-9A-F]{64}$")
    caller_address: str | None = Field(default=None, min_length=40, max_length=40, pattern=r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")
    function_name: str | None = Field(default=None, min_length=1, max_length=160)
    args_count: int | None = Field(default=None, ge=0)
    send_amount: str | None = Field(default=None, min_length=1, max_length=160)
    execution_status: Literal["success", "failed"] | None
    gas_wanted: str | None = Field(default=None, pattern=r"^(0|[1-9][0-9]*)$")
    gas_used: str | None = Field(default=None, pattern=r"^(0|[1-9][0-9]*)$")


class RealmCallsPagination(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(ge=1, le=100)
    next_before_height: int | None = Field(default=None, gt=0)
    next_before_tx_index: int | None = Field(default=None, ge=0)
    next_before_message_index: int | None = Field(default=None, ge=0, le=19)

    @model_validator(mode="after")
    def validate_cursor_tuple(self) -> "RealmCallsPagination":
        if sum(value is None for value in (self.next_before_height, self.next_before_tx_index,
                                           self.next_before_message_index)) not in (0, 3):
            raise ValueError("next cursor fields must be supplied together")
        return self


class RealmCallsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: RealmCallSource
    items: list[RealmCallListItem] = Field(max_length=100)
    pagination: RealmCallsPagination

class RealmNamespaceTopItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    namespace_key: str = Field(min_length=1, max_length=256)
    application: RealmApplicationMetadata | None
    realm_count: int = Field(gt=0)
    called_realm_count: int = Field(gt=0)
    rpc_visible_realm_count: int = Field(gt=0)
    direct_call_count: int = Field(gt=0)
    successful_call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    unknown_result_call_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    first_seen_height: int | None = Field(default=None, gt=0)
    last_activity_height: int | None = Field(default=None, gt=0)
    last_activity_tx_index: int | None = Field(default=None, ge=0)
    last_activity_at: str | None = None
    realms: list[RealmNamespaceMember] = Field(max_length=100)
    realms_truncated: bool

class RealmNamespaceTopResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: RealmRankingSource
    scope: Literal["all", "curated"]
    items: list[RealmNamespaceTopItem] = Field(max_length=10)
