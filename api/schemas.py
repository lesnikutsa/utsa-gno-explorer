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
