"""FastAPI application for the read-only explorer API."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging

from fastapi import FastAPI, HTTPException

from api.config import ConfigError, load_config
from api.database import MissingIndexerStateError, database, isoformat_utc_z
from api.schemas import HealthResponse

LOGGER = logging.getLogger(__name__)
UNAVAILABLE_DETAIL = "Explorer database is unavailable"


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
    return datetime.now(UTC)


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
            checked_at = checked_at.replace(tzinfo=UTC)
        if (now - checked_at.astimezone(UTC)).total_seconds() > config.rpc_check_stale_seconds:
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
