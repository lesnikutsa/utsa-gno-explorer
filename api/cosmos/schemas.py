"""Strict public response contracts for Cosmos network endpoints."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

DecimalString = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")]
SignedDecimalString = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")]
AmountString = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^(0|[1-9][0-9]*)$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectionErrorDetail(StrictModel):
    code: Literal["section_unavailable"]


class SectionError(StrictModel):
    error: SectionErrorDetail


class NetworkOverview(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    family: Literal["cosmos"]
    display_name: str = Field(min_length=1, max_length=64)
    network_name: str = Field(min_length=1, max_length=64)
    chain_id: str = Field(min_length=1, max_length=128)
    operational_state: Literal["healthy", "syncing", "degraded", "unavailable"]
    current_local_height: int = Field(gt=0)
    latest_block_time: str = Field(min_length=20, max_length=64)
    catching_up: bool
    tx_index: Literal["on", "off", "unknown"]
    node_version: str | None = Field(default=None, max_length=256)
    application_name: str | None = Field(default=None, max_length=256)
    application_version: str | None = Field(default=None, max_length=256)
    sdk_version: str | None = Field(default=None, max_length=256)
    cometbft_version: str | None = Field(default=None, max_length=256)
    generated_at: str = Field(min_length=20, max_length=64)
    block_history_state: Literal["unknown", "available", "unavailable"]
    historical_state: Literal["unknown", "available", "unavailable"]


class NativeAsset(StrictModel):
    base: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9/:._-]+$")
    display: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9/:._-]+$")
    symbol: str = Field(min_length=1, max_length=32)
    exponent: int = Field(ge=0, le=18)
    total_supply: AmountString


class AssetsSupply(StrictModel):
    assets: list[NativeAsset] = Field(min_length=1, max_length=16)


class CoinAmount(StrictModel):
    denom: str = Field(min_length=1, max_length=128)
    amount: DecimalString


class Staking(StrictModel):
    bonded_tokens: AmountString
    not_bonded_tokens: AmountString
    bonded_ratio: DecimalString
    active_validator_count: int = Field(ge=0, le=10000)
    max_validators: int = Field(gt=0, le=10000)
    unbonding_time: str = Field(min_length=1, max_length=64)
    max_entries: int = Field(ge=0)
    historical_entries: int = Field(ge=0)
    bond_denom: str = Field(min_length=1, max_length=128)
    min_commission_rate: DecimalString | None = None
    max_commission_rate: DecimalString | None = None
    key_rotation_fee: CoinAmount | None = None


class Mint(StrictModel):
    current_inflation: DecimalString
    inflation_min: DecimalString
    inflation_max: DecimalString
    inflation_rate_change: DecimalString
    goal_bonded: DecimalString
    blocks_per_year: int = Field(gt=0)


class Slashing(StrictModel):
    signed_blocks_window: int = Field(gt=0)
    minimum_signed_per_window: DecimalString
    allowed_missed_threshold: int = Field(ge=0)
    downtime_jail_duration: str = Field(min_length=1, max_length=64)
    double_sign_slash_fraction: DecimalString
    downtime_slash_fraction: DecimalString


class NakamotoBonus(StrictModel):
    enabled: bool
    step: DecimalString
    period_epoch_identifier: str = Field(min_length=1, max_length=64)
    minimum_coefficient: DecimalString
    maximum_coefficient: DecimalString


class Distribution(StrictModel):
    community_tax: DecimalString
    withdraw_address_enabled: bool
    community_pool: dict[str, DecimalString] = Field(max_length=16)
    nakamoto_bonus: NakamotoBonus | None = None


class DecimalRange(StrictModel):
    min: DecimalString
    max: DecimalString


class GovernanceAdvanced(StrictModel):
    law_quorum: DecimalString | None = None
    law_threshold: DecimalString | None = None
    constitution_amendment_quorum: DecimalString | None = None
    constitution_amendment_threshold: DecimalString | None = None
    quorum_range: DecimalRange | None = None
    law_quorum_range: DecimalRange | None = None
    constitution_amendment_quorum_range: DecimalRange | None = None
    quorum_timeout: str | None = Field(default=None, max_length=64)
    maximum_voting_period_extension: str | None = Field(default=None, max_length=64)
    governor_status_change_period: str | None = Field(default=None, max_length=64)
    minimum_governor_self_delegation: DecimalString | None = None


class Governance(StrictModel):
    minimum_deposit: dict[str, DecimalString] = Field(max_length=16)
    maximum_deposit_period: str = Field(min_length=1, max_length=64)
    voting_period: str = Field(min_length=1, max_length=64)
    quorum: DecimalString
    threshold: DecimalString
    advanced: GovernanceAdvanced | None = None


class MissedValidator(StrictModel):
    moniker: str = Field(min_length=1, max_length=256)
    operator_address: str = Field(min_length=1, max_length=90)
    consensus_address: str = Field(min_length=1, max_length=90)
    missed_blocks_counter: int = Field(ge=0)
    start_height: int = Field(ge=0)
    index_offset: int = Field(ge=0)
    jailed: bool
    tombstoned: bool
    remaining_misses_before_threshold: int = Field(ge=0)


class OverviewResponse(StrictModel):
    network: NetworkOverview
    assets_and_supply: AssetsSupply | SectionError
    staking: Staking | SectionError
    mint: Mint | SectionError
    slashing: Slashing | SectionError
    distribution: Distribution | SectionError
    governance: Governance | SectionError
    top_active_validators_by_missed_blocks: list[MissedValidator] | SectionError


class MarketResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    currency: Literal["USD"]
    price: DecimalString
    market_cap: DecimalString
    change_24h: SignedDecimalString
    source_last_updated_at: str = Field(min_length=20, max_length=64)


class CosmosBlock(StrictModel):
    height: int = Field(gt=0)
    hash: str = Field(min_length=2, max_length=128)
    timestamp: str = Field(min_length=20, max_length=64)
    proposer: str = Field(min_length=2, max_length=128)
    transaction_count: int = Field(ge=0)


class BlocksResponse(StrictModel):
    source: Literal["rpc_metadata"]
    blocks: list[CosmosBlock] = Field(max_length=20)


class HeightEta(StrictModel):
    remaining_blocks: int = Field(gt=0)
    average_block_seconds: float = Field(gt=0)
    estimated_at: str = Field(min_length=20, max_length=64)
    sample_intervals: int = Field(ge=20, le=100)


class BlockLookupResponse(StrictModel):
    state: Literal["available", "future", "node_not_synced", "history_unavailable"]
    local_height: int = Field(gt=0)
    source: Literal["rpc"]
    block: CosmosBlock | None = None
    eta: HeightEta | None = None
    eta_unavailable_reason: Literal["insufficient_history", "network_stalled", "date_overflow"] | None = None
