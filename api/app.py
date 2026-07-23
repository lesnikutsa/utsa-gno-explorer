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
    TransactionDetailResponse,
    ValidatorListItem,
    ValidatorSearchItem,
    ValidatorSearchResponse,
    ValidatorCurrentStatus,
    ValidatorDetailResponse,
    ValidatorSigningHistory,
    ValidatorSigningHistoryBatchItem,
    ValidatorSigningHistoryBatchResponse,
    ValidatorSigningHistoryBlock,
    ValidatorSigningHistoryItem,
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


def _normalize_tx_hash(tx_hash_hex: str | None) -> str | None:
    if tx_hash_hex is None:
        return None
    normalized = tx_hash_hex[2:] if tx_hash_hex.startswith(("0x", "0X")) else tx_hash_hex
    normalized = normalized.upper()
    return normalized if re.fullmatch(r"[0-9A-F]{64}", normalized) else None


def _block_summary_from_row(row: dict) -> BlockSummary:
    return BlockSummary(
        height=row["height"],
        block_hash=_normalize_block_hash(row["block_hash_hex"]),
        time=isoformat_utc_z(row["time_utc"]),
        proposer_address=row["proposer_address"],
        proposer_moniker=row.get("proposer_moniker"),
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
        proposer_moniker=block.get("proposer_moniker"),
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
                tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
                raw_base64=row["raw_base64"],
                raw_base64_length=row["raw_base64_length"],
                decoded_byte_length=row["decoded_byte_length"],
                decode_status=row["decode_status"],
            )
            for row in detail["transactions"]
        ],
    )


def _transaction_detail_from_row(row: dict) -> TransactionDetailResponse:
    return TransactionDetailResponse(
        block_height=row["block_height"],
        block_hash=_normalize_block_hash(row["block_hash_hex"]),
        block_time=isoformat_utc_z(row["time_utc"]),
        proposer_address=row["proposer_address"],
        proposer_moniker=row.get("proposer_moniker"),
        index=row["tx_index"],
        tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
        raw_base64=row["raw_base64"],
        raw_base64_length=row["raw_base64_length"],
        decoded_byte_length=row["decoded_byte_length"],
        decode_status=row["decode_status"],
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
                "proposer_moniker": row.get("proposer_moniker"),
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
            moniker=row.get("moniker"),
            operator_address=row.get("operator_address"),
            server_type=row.get("server_type"),
            valoper_source_height=row.get("valoper_source_height"),
            uptime_20=uptimes[20],
            uptime_100=uptimes[100],
        ))
    return ValidatorsResponse(
        height=checkpoint["height"], total=len(items),
        total_voting_power=str(total_voting_power), items=items,
    )


def _history_status(row: dict) -> str:
    if row["membership_address"] is None:
        return "not_active"
    if row["signature_address"] is None:
        return "unknown"
    if row["signed"] is True:
        return "commit"
    if row["vote_status"] in ("nil", "absent", "invalid"):
        return row["vote_status"]
    return "unknown"


def _uptime_from_history(items: list[ValidatorSigningHistoryItem]) -> ValidatorUptime:
    statuses = [item.status for item in items]
    active = sum(status != "not_active" for status in statuses)
    counts = {status: statuses.count(status) for status in ("commit", "nil", "absent", "invalid", "unknown")}
    return ValidatorUptime(
        network_blocks=len(items),
        active_blocks=active,
        signed_blocks=counts["commit"],
        nil_blocks=counts["nil"],
        absent_blocks=counts["absent"],
        invalid_blocks=counts["invalid"],
        unknown_blocks=counts["unknown"],
        uptime_percent=_rounded_percent(counts["commit"], active),
    )


def _validator_detail_from_rows(result: dict) -> ValidatorDetailResponse:
    identity = result["identity"]
    current_row = result["current"]
    active = current_row["voting_power"] is not None
    history_items = [
        ValidatorSigningHistoryItem(
            height=row["height"], time=isoformat_utc_z(row["time_utc"]), status=_history_status(row)
        )
        for row in result["history"]
    ]
    heights = [item.height for item in history_items]
    current_power = current_row["voting_power"]
    return ValidatorDetailResponse(
        address=identity["address"],
        public_key_type=identity["public_key_type"],
        public_key_value=identity["public_key_value"],
        first_seen_height=identity["first_seen_height"],
        last_seen_height=identity["last_seen_height"],
        moniker=identity.get("moniker"),
        operator_address=identity.get("operator_address"),
        signing_pubkey=identity.get("signing_pubkey"),
        description=identity.get("description"),
        server_type=identity.get("server_type"),
        valoper_source_height=identity.get("valoper_source_height"),
        current=ValidatorCurrentStatus(
            active=active,
            height=current_row["height"],
            voting_power=str(current_power) if active else None,
            voting_power_percent=_rounded_percent(current_power, current_row["total_voting_power"]) if active else 0.0,
            proposer_priority=(None if not active or current_row["proposer_priority"] is None
                               else str(current_row["proposer_priority"])),
        ),
        uptime_20=_uptime_from_history(history_items[-20:]),
        uptime_100=_uptime_from_history(history_items),
        signing_history=ValidatorSigningHistory(
            network_blocks=len(history_items),
            start_height=min(heights) if heights else None,
            end_height=max(heights) if heights else None,
            items=history_items,
        ),
    )


def _validator_signing_history_batch_from_rows(result: dict) -> ValidatorSigningHistoryBatchResponse:
    block_rows = result["blocks"]
    block_heights = [row["height"] for row in block_rows]
    if block_heights != sorted(block_heights) or len(block_heights) != len(set(block_heights)):
        raise ValueError("Signing history block axis is invalid")

    expected_addresses = list(result["checkpoint"]["validator_addresses"])
    if len(expected_addresses) != len(set(expected_addresses)):
        raise ValueError("Signing history validator axis contains duplicates")
    expected_address_set = set(expected_addresses)

    grouped: dict[str, list[dict]] = {}
    for row in result["items"]:
        if row["address"] not in expected_address_set:
            raise ValueError("Signing history matrix contains an unexpected validator")
        grouped.setdefault(row["address"], []).append(row)

    items = []
    for address in expected_addresses:
        rows = grouped.get(address, [])
        if [row["height"] for row in rows] != block_heights:
            raise ValueError("Signing history matrix is not aligned")
        items.append(ValidatorSigningHistoryBatchItem(
            address=address,
            statuses=[_history_status(row) for row in rows],
        ))

    blocks = [
        ValidatorSigningHistoryBlock(height=row["height"], time=isoformat_utc_z(row["time_utc"]))
        for row in block_rows
    ]
    return ValidatorSigningHistoryBatchResponse(
        height=result["checkpoint"]["height"],
        network_blocks=len(blocks),
        start_height=block_heights[0] if block_heights else None,
        end_height=block_heights[-1] if block_heights else None,
        blocks=blocks,
        items=items,
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


@app.get("/api/search/validators", response_model=ValidatorSearchResponse)
def search_validators(
    q: str = Query(min_length=1),
    limit: int = Query(default=6, ge=1, le=10),
) -> ValidatorSearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="q must contain at least 2 non-whitespace characters")
    if len(query) > 128:
        raise HTTPException(status_code=422, detail="q must contain at most 128 characters")
    try:
        rows = database.fetch_validator_search(query, limit)
    except Exception:
        LOGGER.error("Explorer database validator search query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return ValidatorSearchResponse(items=[ValidatorSearchItem(**row) for row in rows])


@app.get("/api/validators/signing-history", response_model=ValidatorSigningHistoryBatchResponse)
def get_validator_signing_history(
    limit: int = Query(default=100, ge=1, le=100),
) -> ValidatorSigningHistoryBatchResponse:
    try:
        result = database.fetch_validator_signing_history(limit=limit)
        return _validator_signing_history_batch_from_rows(result)
    except Exception:
        LOGGER.error("Explorer database validator signing history query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/validators/{address}", response_model=ValidatorDetailResponse)
def get_validator_detail(address: str = Path(min_length=1, max_length=128)) -> ValidatorDetailResponse:
    try:
        result = database.fetch_validator_detail(address)
        if result is None:
            raise HTTPException(status_code=404, detail="Validator not found")
        return _validator_detail_from_rows(result)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database validator detail query failed")
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


@app.get("/api/blocks/{height}/transactions/{index}", response_model=TransactionDetailResponse)
def get_transaction_detail(
    height: int = Path(gt=0),
    index: int = Path(ge=0),
) -> TransactionDetailResponse:
    try:
        row = database.fetch_transaction_detail(height, index)
    except Exception:
        LOGGER.error("Explorer database transaction detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _transaction_detail_from_row(row)


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
