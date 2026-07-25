"""Bounded, sequential maintenance of persisted transaction summaries."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from .transaction_summary import normalize_summary

MAX_LIMIT = 100
BACKFILL_ADVISORY_LOCK_KEY = 0x5554534154584246

GENERIC_PREDICATE_SQL = """(
    payload_summary IS NULL OR (
        payload_summary->>'schema_version' = '1'
        AND payload_summary->>'chain_family' = 'unknown'
        AND payload_summary->>'parse_status' = 'unparsed'
    )
)"""

CANDIDATE_SQL = f"""
SELECT id, block_height, tx_index, raw_base64, decoded_byte_length
FROM transactions
WHERE decode_status = 'decoded'
  AND raw_base64 IS NOT NULL
  AND raw_base64 ~ '^(?:[A-Za-z0-9+/]{{4}})*(?:[A-Za-z0-9+/]{{2}}==|[A-Za-z0-9+/]{{3}}=)?$'
  AND decoded_byte_length IS NOT NULL
  AND decoded_byte_length >= 0
  AND {GENERIC_PREDICATE_SQL}
ORDER BY block_height DESC, tx_index DESC
LIMIT %s
"""

UPDATE_SQL = f"""
UPDATE transactions
SET payload_summary = %s
WHERE id = %s AND {GENERIC_PREDICATE_SQL}
"""


@dataclass(frozen=True)
class Candidate:
    id: int
    block_height: int
    tx_index: int
    raw_base64: str
    decoded_byte_length: int


@dataclass
class BackfillResult:
    selected: int = 0
    decoded: int = 0
    parsed: int = 0
    unsupported: int = 0
    updated: int = 0
    dry_run: int = 0
    decode_failed: int = 0
    skipped_race: int = 0


def select_candidates(connection, limit: int) -> list[Candidate]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit must be between 1 and 100")
    with connection.cursor() as cursor:
        cursor.execute(CANDIDATE_SQL, (limit,))
        return [Candidate(int(row[0]), int(row[1]), int(row[2]), row[3], int(row[4])) for row in cursor.fetchall()]


def conditional_update(connection, candidate_id: int, summary: dict) -> bool:
    normalized = normalize_summary(summary)
    if normalized["parse_status"] not in {"parsed", "unsupported"}:
        raise ValueError("decoder summary is not a stable result")
    with connection.cursor() as cursor:
        cursor.execute(UPDATE_SQL, (json.dumps(normalized, separators=(",", ":")), candidate_id))
        return cursor.rowcount == 1


def process_candidates(
    connection, decoder, candidates: Sequence[Candidate], *, apply: bool,
    sleep_ms: int, progress: Callable[[Candidate, str], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> BackfillResult:
    result = BackfillResult(selected=len(candidates))
    for position, candidate in enumerate(candidates):
        summary = decoder.decode(candidate.raw_base64, candidate.decoded_byte_length)
        if summary is None:
            result.decode_failed += 1
            outcome = "decode_failed"
        else:
            normalized = normalize_summary(summary)
            status = normalized["parse_status"]
            if status not in {"parsed", "unsupported"}:
                result.decode_failed += 1
                outcome = "decode_failed"
            else:
                result.decoded += 1
                setattr(result, status, getattr(result, status) + 1)
                outcome = status
                if apply:
                    if conditional_update(connection, candidate.id, normalized):
                        result.updated += 1
                        outcome = "updated"
                    else:
                        result.skipped_race += 1
                        outcome = "skipped_race"
                else:
                    result.dry_run += 1
        if progress is not None:
            progress(candidate, outcome)
        if position + 1 < len(candidates) and sleep_ms:
            sleeper(sleep_ms / 1000)
    return result


def try_advisory_lock(connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (BACKFILL_ADVISORY_LOCK_KEY,))
        return bool(cursor.fetchone()[0])


def release_advisory_lock(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (BACKFILL_ADVISORY_LOCK_KEY,))
