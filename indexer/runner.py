"""Foreground continuous indexer runner with bounded catch-up."""
from __future__ import annotations

import hashlib
import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

from scripts.inspect_rpc import RpcError

from .database import ChainIdentityError, DatabaseError, FinalizedDataConflict, PostgresDatabase
from .parsers import parse_height
from .rpc import fetch_height, select_rpc

LOGGER = logging.getLogger(__name__)


class FatalIndexerError(RuntimeError):
    """Raised when the continuous indexer must exit non-zero immediately."""


class TransientIndexerError(RuntimeError):
    """Raised when the continuous indexer can retry after bounded backoff."""


class AdvisoryLockHeld(FatalIndexerError):
    """Raised when another continuous indexer already holds the chain lock."""


class StopController:
    def __init__(self) -> None:
        self.requested = False
        self.reason: str | None = None

    def request_stop(self, reason: str) -> None:
        self.requested = True
        self.reason = reason


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class ContinuousConfig:
    start_height: int | None
    batch_size: int
    poll_interval_seconds: int
    error_backoff_seconds: int
    max_backoff_seconds: int
    once: bool = False
    max_cycles: int | None = None


@dataclass(frozen=True)
class CycleResult:
    processed: list[int]
    checkpoint_before: int | None
    checkpoint_after: int | None
    finalized_tip: int
    planned_start: int | None
    planned_end: int | None


def validate_continuous_config(config: ContinuousConfig) -> None:
    positive = {
        "batch_size": config.batch_size,
        "poll_interval_seconds": config.poll_interval_seconds,
        "error_backoff_seconds": config.error_backoff_seconds,
        "max_backoff_seconds": config.max_backoff_seconds,
    }
    for name, value in positive.items():
        if value < 1:
            raise FatalIndexerError(f"{name} must be positive")
    if config.start_height is not None and config.start_height < 1:
        raise FatalIndexerError("start_height must be positive")
    if config.max_cycles is not None and config.max_cycles < 1:
        raise FatalIndexerError("max_cycles must be positive")
    if config.error_backoff_seconds > config.max_backoff_seconds:
        raise FatalIndexerError("error_backoff_seconds must be <= max_backoff_seconds")


def sanitized_url(url: str) -> str:
    parsed = urlsplit(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def advisory_lock_key(chain_id: str) -> int:
    digest = hashlib.blake2b(chain_id.encode("utf-8"), digest_size=8, person=b"utsa-gno").digest()
    value = int.from_bytes(digest, "big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


class AdvisoryLock:
    def __init__(self, database: PostgresDatabase, chain_id: str) -> None:
        self.database = database
        self.chain_id = chain_id
        self.connection = None
        self.key = advisory_lock_key(chain_id)

    def acquire(self) -> None:
        self.connection = self.database.connect()
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
            row = cursor.fetchone()
        if not row or not row[0]:
            self.close()
            raise AdvisoryLockHeld(f"continuous indexer advisory lock is already held for chain_id={self.chain_id}")

    def close(self) -> None:
        if self.connection is not None:
            try:
                with self.connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
                self.connection.commit()
            finally:
                self.connection.close()
                self.connection = None


def run_cycle(database, chain_id: str, rpc_urls: list[str], max_height_lag: int, config: ContinuousConfig, stop: StopController) -> CycleResult:
    selected = select_rpc(rpc_urls, chain_id, max_height_lag)
    database.record_rpc_probe_cycle(chain_id, selected.probes)
    checkpoint = database.get_checkpoint(chain_id)
    LOGGER.info("selected_rpc=%s latest_rpc_height=%s finalized_tip=%s checkpoint_before=%s", sanitized_url(selected.client.base_url), selected.latest_height, selected.finalized_tip, checkpoint)
    if checkpoint is None and config.start_height is None:
        raise FatalIndexerError("--start-height or INDEXER_START_HEIGHT is required for an empty database")
    next_height = config.start_height if checkpoint is None else checkpoint + 1
    if next_height > selected.finalized_tip:
        LOGGER.info("caught up: checkpoint=%s finalized_tip=%s", checkpoint, selected.finalized_tip)
        return CycleResult([], checkpoint, checkpoint, selected.finalized_tip, None, None)
    end_height = min(selected.finalized_tip, next_height + config.batch_size - 1)
    LOGGER.info("planned_range=%s-%s", next_height, end_height)
    processed: list[int] = []
    for height in range(next_height, end_height + 1):
        if stop.requested:
            break
        block_payload, commit_payload, validators_payload = fetch_height(selected.client, height)
        parsed = parse_height(height, block_payload, commit_payload, validators_payload)
        database.write_height(parsed, chain_id, selected.finalized_tip)
        processed.append(height)
    checkpoint_after = database.get_checkpoint(chain_id)
    return CycleResult(processed, checkpoint, checkpoint_after, selected.finalized_tip, next_height, end_height)


def run_continuous(database: PostgresDatabase, chain_id: str, rpc_urls: list[str], max_height_lag: int, config: ContinuousConfig, stop: StopController | None = None, sleep: Sleeper = time.sleep, lock_factory: Callable[[PostgresDatabase, str], AdvisoryLock] = AdvisoryLock) -> int:
    validate_continuous_config(config)
    stop = stop or StopController()
    lock = lock_factory(database, chain_id)
    cycle = 0
    backoff = config.error_backoff_seconds
    reason = "completed"
    try:
        lock.acquire()
        while not stop.requested:
            if config.max_cycles is not None and cycle >= config.max_cycles:
                reason = "max-cycles reached"
                break
            cycle += 1
            LOGGER.info("cycle=%s starting", cycle)
            try:
                result = run_cycle(database, chain_id, rpc_urls, max_height_lag, config, stop)
            except (FinalizedDataConflict, ChainIdentityError) as exc:
                raise FatalIndexerError(str(exc)) from exc
            except (RpcError, DatabaseError, OSError) as exc:
                checkpoint = _safe_checkpoint(database, chain_id)
                next_retry = None if checkpoint is None else checkpoint + 1
                LOGGER.warning("transient error: %s; retry_height=%s backoff=%ss", exc, next_retry, backoff)
                sleep(backoff)
                backoff = min(config.max_backoff_seconds, backoff * 2)
                continue
            LOGGER.info("cycle=%s processed_heights=%s checkpoint_after=%s", cycle, result.processed, result.checkpoint_after)
            if result.processed:
                backoff = config.error_backoff_seconds
            if config.once:
                reason = "once completed"
                break
            if stop.requested:
                reason = stop.reason or "stop requested"
                break
            if not result.processed:
                LOGGER.info("sleep reason=caught-up duration=%ss", config.poll_interval_seconds)
                sleep(config.poll_interval_seconds)
        if stop.requested:
            reason = stop.reason or "stop requested"
        final_checkpoint = _safe_checkpoint(database, chain_id)
        LOGGER.info("shutdown reason=%s final_checkpoint=%s", reason, final_checkpoint)
        return 0
    except (FatalIndexerError, ValueError, DatabaseError) as exc:
        LOGGER.error("fatal continuous indexer error: %s", exc)
        return 1
    finally:
        lock.close()


def _safe_checkpoint(database, chain_id: str) -> int | None:
    try:
        return database.get_checkpoint(chain_id)
    except Exception:
        return None


def install_signal_handlers(stop: StopController) -> None:
    def handler(signum, _frame):
        stop.request_stop(signal.Signals(signum).name)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
