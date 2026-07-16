"""Database pool and read-only query helpers for the API."""

from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.config import ApiConfig

HEALTH_SQL = """
SELECT
    s.chain_id,
    s.last_finalized_height AS indexed_height,
    s.finalized_tip_height,
    (
        SELECT max(r.last_checked_at)
        FROM rpc_endpoints r
        WHERE r.chain_id = s.chain_id
          AND r.is_enabled = %s
    ) AS rpc_last_checked_at
FROM indexer_state s
WHERE s.state_key = %s
"""


class MissingIndexerStateError(RuntimeError):
    """Raised when the singleton indexer state row is missing."""


class ApiDatabase:
    def __init__(self) -> None:
        self.pool: ConnectionPool[Any] | None = None

    def open(self, config: ApiConfig) -> None:
        if self.pool is not None:
            return
        pool = ConnectionPool(
            conninfo=config.database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        try:
            pool.open(wait=False)
        except Exception:
            pool.close()
            raise
        self.pool = pool

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            self.pool = None

    def fetch_health_row(self) -> dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(HEALTH_SQL, (True, "default"))
                row = cursor.fetchone()
        if row is None:
            raise MissingIndexerStateError("Default indexer state is missing")
        return dict(row)


database = ApiDatabase()


def isoformat_utc_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
