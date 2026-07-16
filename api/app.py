"""FastAPI application for the read-only explorer API."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import re
from decimal import Decimal, ROUND_HALF_UP

from fastapi import FastAPI, HTTPException, Path, Query

from api.config import ConfigError, load_config
from api.database import (
    MissingIndexedBlockError,
    MissingIndexerStateError,
    database,
    isoformat_utc_z,
)
from api.schemas import (
    BlockCommitSummary,
    BlockDetailResponse,
    BlockSummary,
    BlocksPagination,
    BlockTransactionSummary,
    BlocksResponse,
    HealthResponse,
    NetworkResponse,
    NetworkValidators,
    SelectedRpc,
    ValidatorListItem,
    ValidatorsResponse,
    ValidatorUptime,
)

LOGGER = logging.getLogger(__name__)
UNAVAILABLE_DETAIL = "Explorer database is unavailable"
HEX_HASH_RE = re.compile(r"^(?:0[xX])?([0-9a-fA-F]{64})$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        config = load_config()
        database.open(config)
        app.state.api_config = config
    except ConfigError as exc:
        LOGGER.error("API configuration error: %s", exc)
        raise RuntimeError("API configuration error") from None
    except Exception:
        LOGGER.error("Explorer database startup failed")
        raise RuntimeError(UNAVAILABLE_DETAIL) from None
    try:
        yield
    finally:
        database.close()


app = FastAPI(title="UTSA Gno.land Explorer API", lifespan=lifespan)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_block_hash(block_hash_hex: str) -> str:
    if block_hash_hex.startswith(("0x", "0X")):
        block_hash_hex = block_hash_hex[2:]
    return block_hash_hex.upper()


def _block_summary_from_row(row: dict) -> BlockSummary:
    return BlockSummary(
        height=row["height"],
        block_hash=_normalize_block_hash(row["block_hash_hex"]),
        time=isoformat_utc_z(row["time_utc"]),
        proposer_address=row["proposer_address"],
        tx_count=row["tx_count"],
    )


def _block_detail_from_row(detail: dict) -> BlockDetailResponse:
    block = detail["block"]
    commit = detail["commit"]
    return BlockDetailResponse(
        height=block["height"],
        block_hash=_normalize_block_hash(block["block_hash_hex"]),
        block_hash_base64=block["block_hash_base64"],
        time=isoformat_utc_z(block["time_utc"]),
        proposer_address=block["proposer_address"],
        tx_count=block["tx_count"],
        commit=BlockCommitSummary(
            validators=commit["validators"],
            signed=commit["signed"],
            missed=commit["missed"],
            nil=commit["nil"],
            absent=commit["absent"],
            invalid=commit["invalid"],
            unknown=commit["unknown"],
        ),
        transactions=[
            BlockTransactionSummary(
                index=row["tx_index"],
                raw_base64=row["raw_base64"],
                raw_base64_length=row["raw_base64_length"],
                decoded_byte_length=row["decoded_byte_length"],
                decode_status=row["decode_status"],
            )
            for row in detail["transactions"]
        ],
    )


def _health_response_from_row(row: dict, config) -> HealthResponse:
    indexed_height = row["indexed_height"]
    finalized_tip_height = row["finalized_tip_height"]
    indexer_lag = None
    if finalized_tip_height is not None:
        indexer_lag = max(finalized_tip_height - indexed_height, 0)

    rpc_last_checked_at = row["rpc_last_checked_at"]
    degraded = False
    if indexer_lag is not None and indexer_lag > config.indexer_lag_degraded_threshold:
        degraded = True
    if not row["has_healthy_rpc"]:
        degraded = True
    if rpc_last_checked_at is None:
        degraded = True
    else:
        now = utc_now()
        checked_at = rpc_last_checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if (now - checked_at.astimezone(timezone.utc)).total_seconds() > config.rpc_check_stale_seconds:
            degraded = True

    return HealthResponse(
        status="degraded" if degraded else "ok",
        database="ok",
        chain_id=row["chain_id"],
        indexed_height=indexed_height,
        finalized_tip_height=finalized_tip_height,
        indexer_lag=indexer_lag,
        rpc_last_checked_at=isoformat_utc_z(rpc_last_checked_at),
        api_version=config.api_version,
    )


def _network_response_from_row(row: dict) -> NetworkResponse:
    indexed_height = row["indexed_height"]
    finalized_tip_height = row["finalized_tip_height"]
    indexer_lag = None
    if finalized_tip_height is not None:
        indexer_lag = max(finalized_tip_height - indexed_height, 0)

    selected_rpc = None
    if row["rpc_url"] is not None:
        selected_rpc = SelectedRpc(
            url=row["rpc_url"],
            healthy=row["rpc_healthy"],
            catching_up=row["rpc_catching_up"],
            observed_height=row["rpc_observed_height"],
            lag=row["rpc_lag"],
            last_checked_at=isoformat_utc_z(row["rpc_last_checked_at"]),
        )

    return NetworkResponse(
        chain_id=row["chain_id"],
        rpc_height=row["rpc_observed_height"] if selected_rpc is not None else None,
        finalized_tip_height=finalized_tip_height,
        indexed_height=indexed_height,
        indexer_lag=indexer_lag,
        latest_block=_block_summary_from_row(
            {
                "height": row["block_height"],
                "block_hash_hex": row["block_hash_hex"],
                "time_utc": row["time_utc"],
                "proposer_address": row["proposer_address"],
                "tx_count": row["tx_count"],
            }
        ),
        validators=NetworkValidators(
            height=indexed_height,
            active_count=row["validator_active_count"],
            total_voting_power=str(row["validator_total_voting_power"]),
        ),
        selected_rpc=selected_rpc,
    )


def _normalize_hash_query(value: str) -> tuple[str | None, str | None]:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="hash must not be empty")
    if len(stripped) > 200:
        raise HTTPException(status_code=422, detail="hash is too long")
    match = HEX_HASH_RE.match(stripped)
    if match is not None:
        return match.group(1).upper(), None
    return None, stripped


def _rounded_percent(numerator: Decimal | int, denominator: Decimal | int) -> float:
    if denominator == 0:
        return 0.0
    value = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _validators_response_from_rows(result: dict) -> ValidatorsResponse:
    rows = result["items"]
    total_voting_power = sum((Decimal(row["voting_power"]) for row in rows), Decimal(0))
    checkpoint = result["checkpoint"]
    items = []
    for row in rows:
        uptimes = {}
        for window in (20, 100):
            active = int(row[f"active_blocks_{window}"])
            signed = int(row[f"signed_blocks_{window}"])
            uptimes[window] = ValidatorUptime(
                network_blocks=int(checkpoint[f"network_blocks_{window}"]),
                active_blocks=active,
                signed_blocks=signed,
                nil_blocks=int(row[f"nil_blocks_{window}"]),
                absent_blocks=int(row[f"absent_blocks_{window}"]),
                invalid_blocks=int(row[f"invalid_blocks_{window}"]),
                unknown_blocks=int(row[f"unknown_blocks_{window}"]),
                uptime_percent=_rounded_percent(signed, active),
            )
        items.append(ValidatorListItem(
            address=row["address"],
            public_key_type=row["public_key_type"],
            voting_power=str(row["voting_power"]),
            percent=_rounded_percent(row["voting_power"], total_voting_power),
            proposer_priority=None if row["proposer_priority"] is None else str(row["proposer_priority"]),
            uptime_20=uptimes[20],
            uptime_100=uptimes[100],
        ))
    return ValidatorsResponse(
        height=checkpoint["height"], total=len(items),
        total_voting_power=str(total_voting_power), items=items,
    )


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    config = app.state.api_config
    try:
        row = database.fetch_health_row()
    except MissingIndexerStateError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    except Exception:
        LOGGER.error("Explorer database health query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return _health_response_from_row(row, config)


@app.get("/api/network", response_model=NetworkResponse)
def get_network() -> NetworkResponse:
    try:
        row = database.fetch_network_overview()
    except (MissingIndexerStateError, MissingIndexedBlockError):
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    except Exception:
        LOGGER.error("Explorer database network query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return _network_response_from_row(row)


@app.get("/api/validators", response_model=ValidatorsResponse)
def get_validators() -> ValidatorsResponse:
    try:
        return _validators_response_from_rows(database.fetch_active_validators())
    except Exception:
        LOGGER.error("Explorer database validators query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/blocks", response_model=BlocksResponse)
def get_blocks(
    limit: int = Query(default=20, ge=1, le=100),
    before_height: int | None = Query(default=None, gt=0),
    hash: str | None = Query(default=None, max_length=200),
) -> BlocksResponse:
    if before_height is not None and hash is not None:
        raise HTTPException(status_code=422, detail="before_height and hash are mutually exclusive")

    try:
        if hash is not None:
            normalized_hex, block_hash_base64 = _normalize_hash_query(hash)
            row = database.fetch_block_by_hash(
                normalized_hex=normalized_hex,
                block_hash_base64=block_hash_base64,
            )
            items = [] if row is None else [_block_summary_from_row(row)]
            return BlocksResponse(
                items=items,
                pagination=BlocksPagination(limit=limit, next_before_height=None),
            )

        rows = database.fetch_blocks(limit=limit, before_height=before_height)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database blocks query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None

    page_rows = rows[:limit]
    next_before_height = page_rows[-1]["height"] if len(rows) > limit and page_rows else None
    return BlocksResponse(
        items=[_block_summary_from_row(row) for row in page_rows],
        pagination=BlocksPagination(limit=limit, next_before_height=next_before_height),
    )


@app.get("/api/blocks/{height}", response_model=BlockDetailResponse)
def get_block_detail(height: int = Path(gt=0)) -> BlockDetailResponse:
    try:
        detail = database.fetch_block_detail(height)
    except Exception:
        LOGGER.error("Explorer database block detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if detail is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_detail_from_row(detail)
