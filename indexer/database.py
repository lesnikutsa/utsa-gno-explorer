"""PostgreSQL writes for the bounded indexer."""
from __future__ import annotations

import json
import math
import numbers
import re
from dataclasses import dataclass
from typing import Any

from .rpc import RpcProbeResult
from .transaction_summary import normalize_summary
from .transaction_participants import extract_transaction_participants
from .realm_catalog import aggregate_block, extract_realm_calls
from .valopers_persistence import ValopersPersistenceResult, replace_valopers_snapshot_cursor
from .valopers_snapshot import ValopersSnapshot
from .governance_persistence import (GovernancePersistenceResult,
    persist_governance_incremental_cursor, persist_governance_snapshot_cursor)
from governance.gno import GovernanceDiscovery, GovernanceListDiscovery


class DatabaseError(RuntimeError):
    """Raised for database configuration or write failures."""


class FinalizedDataConflict(DatabaseError):
    """Raised when existing finalized data conflicts with reprocessed RPC data."""


class ChainIdentityError(DatabaseError):
    """Raised when persisted chain identity does not match runtime configuration."""


class RealmActivityCoverageError(DatabaseError):
    """Raised when Realm activity coverage cannot be advanced safely."""


class RealmCallCoverageError(DatabaseError):
    """Raised when Realm call index coverage cannot be advanced safely."""


REALM_CALL_INDEX_LOCK_ID = 0x52434C4C494458


@dataclass(frozen=True)
class RealmActivityCoverageResult:
    previous_through_height: int | None
    new_through_height: int | None
    advanced: bool


@dataclass(frozen=True)
class RealmCallCoverageResult:
    previous_through_height: int | None
    new_through_height: int | None
    advanced: bool


@dataclass(frozen=True)
class CheckpointAnchor:
    height: int
    block_hash_hex: str


class PostgresDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.selected_rpc_endpoint_id: int | None = None

    def connect(self):
        if not self.database_url:
            raise DatabaseError("DATABASE_URL is required for write mode; use --dry-run to run without PostgreSQL")
        try:
            import psycopg
        except ImportError as exc:
            raise DatabaseError("Install dependencies from requirements.txt to enable PostgreSQL write mode") from exc
        return psycopg.connect(self.database_url)

    def get_checkpoint(self, chain_id: str) -> int | None:
        with self.connect() as connection, connection.cursor() as cursor:
            return get_checkpoint_cursor(cursor, chain_id)

    def get_checkpoint_anchor(self, chain_id: str) -> CheckpointAnchor | None:
        with self.connect() as connection, connection.cursor() as cursor:
            return get_checkpoint_anchor_cursor(cursor, chain_id)

    def get_selected_rpc_url(self, chain_id: str) -> str | None:
        """Return the enabled persisted selection for one chain."""
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT url FROM rpc_endpoints WHERE chain_id = %s AND is_selected AND is_enabled LIMIT 1",
                (chain_id,),
            )
            row = cursor.fetchone()
        return str(row[0]) if row else None

    def record_rpc_probe_cycle(self, chain_id: str, probes: list[RpcProbeResult]) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.selected_rpc_endpoint_id = record_rpc_probe_cycle_cursor(cursor, chain_id, probes)
            connection.commit()

    def select_rpc_endpoint(self, chain_id: str, probe: RpcProbeResult, reason: str) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                endpoint_id = select_rpc_endpoint_cursor(cursor, chain_id, probe, reason)
            connection.commit()
        self.selected_rpc_endpoint_id = endpoint_id

    def record_rpc_runtime_failure(self, chain_id: str, probe: RpcProbeResult, reason: str) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                _, was_selected = record_rpc_runtime_failure_cursor(cursor, chain_id, probe, reason)
            connection.commit()
        if was_selected:
            self.selected_rpc_endpoint_id = None

    def write_height(self, parsed, chain_id: str, finalized_tip: int) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                write_height_cursor(cursor, parsed, chain_id, finalized_tip, self.selected_rpc_endpoint_id)
            connection.commit()

    def replace_valopers_snapshot(
        self, snapshot: ValopersSnapshot, chain_id: str
    ) -> ValopersPersistenceResult:
        """Atomically replace the current complete Valopers snapshot."""
        with self.connect() as connection:
            with connection.cursor() as cursor:
                result = replace_valopers_snapshot_cursor(cursor, snapshot, chain_id)
            connection.commit()
        return result

    def persist_governance_snapshot(
        self, discovery: GovernanceDiscovery, chain_id: str
    ) -> GovernancePersistenceResult:
        """Atomically persist one complete fixed-height governance snapshot."""
        with self.connect() as connection:
            with connection.cursor() as cursor:
                result = persist_governance_snapshot_cursor(cursor, discovery, chain_id)
            connection.commit()
        return result

    def governance_statuses(self, chain_id: str, realm_path: str) -> dict[int, str]:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT proposal_id,status FROM governance_proposals WHERE chain_id=%s AND realm_path=%s", (chain_id, realm_path))
            return dict(cursor.fetchall())

    def persist_governance_incremental(self, listed: GovernanceListDiscovery,
                                       targeted: list[GovernanceDiscovery], chain_id: str):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                result = persist_governance_incremental_cursor(cursor, listed, targeted, chain_id)
            connection.commit()
        return result


def get_checkpoint_cursor(cursor, chain_id: str) -> int | None:
    cursor.execute("SELECT chain_id, last_finalized_height FROM indexer_state WHERE state_key = %s", ("default",))
    row = cursor.fetchone()
    if row is None:
        return None
    existing_chain_id, last_finalized_height = row
    if existing_chain_id != chain_id:
        raise ChainIdentityError(f"Existing indexer_state chain_id={existing_chain_id} does not match configured chain_id={chain_id}")
    return int(last_finalized_height)



def get_checkpoint_anchor_cursor(cursor, chain_id: str) -> CheckpointAnchor | None:
    cursor.execute("""
        SELECT s.chain_id, s.last_finalized_height, b.block_hash_hex
        FROM indexer_state s LEFT JOIN blocks b ON b.height = s.last_finalized_height
        WHERE s.state_key = %s
    """, ("default",))
    row = cursor.fetchone()
    if row is None:
        return None
    if row[0] != chain_id:
        raise ChainIdentityError(f"Existing indexer_state chain_id={row[0]} does not match configured chain_id={chain_id}")
    block_hash_hex = row[2]
    if block_hash_hex is None:
        raise DatabaseError(f"Checkpoint block is missing at height {row[1]}")
    if not isinstance(block_hash_hex, str) or re.fullmatch(r"[0-9A-F]{64}", block_hash_hex) is None:
        raise DatabaseError(f"Checkpoint block hash is malformed at height {row[1]}")
    return CheckpointAnchor(int(row[1]), block_hash_hex)

def record_rpc_probe_cycle_cursor(cursor, chain_id: str, probes: list[RpcProbeResult]) -> int | None:
    selected_probe = next((probe for probe in probes if probe.selected), None)

    configured_urls = [probe.url for probe in probes]
    cursor.execute(
        "UPDATE rpc_endpoints SET is_enabled = false, is_selected = false, updated_at = now() WHERE chain_id = %s AND NOT (url = ANY(%s))",
        (chain_id, configured_urls),
    )
    endpoint_ids: dict[str, int] = {}
    previous_selected_id = _current_selected_endpoint_id(cursor, chain_id)
    for probe in probes:
        endpoint_ids[probe.url] = _upsert_rpc_endpoint(cursor, chain_id, probe, selected=False)

    selected_endpoint_id = endpoint_ids[selected_probe.url] if selected_probe is not None else None
    switch_reason = "RPC endpoint switch" if selected_endpoint_id is not None and previous_selected_id not in (None, selected_endpoint_id) else None
    if selected_probe is not None and selected_endpoint_id is not None:
        cursor.execute("UPDATE rpc_endpoints SET is_selected = false, updated_at = now() WHERE chain_id = %s AND is_selected", (chain_id,))
        _mark_rpc_endpoint_selected(cursor, selected_endpoint_id, selected_probe)

    for probe in probes:
        _insert_rpc_endpoint_check(cursor, endpoint_ids[probe.url], chain_id, probe, switch_reason if probe.selected else None)
    return selected_endpoint_id



def select_rpc_endpoint_cursor(cursor, chain_id: str, probe: RpcProbeResult, reason: str) -> int:
    endpoint_id = _upsert_rpc_endpoint(cursor, chain_id, probe, selected=False)
    current_id = _current_selected_endpoint_id(cursor, chain_id)
    if current_id == endpoint_id:
        _mark_rpc_endpoint_selected(cursor, endpoint_id, probe)
        return endpoint_id
    cursor.execute("UPDATE rpc_endpoints SET is_selected = false, updated_at = now() WHERE chain_id = %s AND is_selected", (chain_id,))
    _mark_rpc_endpoint_selected(cursor, endpoint_id, probe)
    selected_probe = RpcProbeResult(**{**probe.__dict__, "selected": True})
    _insert_rpc_endpoint_check(cursor, endpoint_id, chain_id, selected_probe, reason[:80])
    return endpoint_id


def record_rpc_runtime_failure_cursor(cursor, chain_id: str, probe: RpcProbeResult, reason: str) -> tuple[int, bool]:
    current_id = _current_selected_endpoint_id(cursor, chain_id)
    failed_probe = RpcProbeResult(**{
        **probe.__dict__, "healthy": False, "selected": False,
        "error_message": reason[:80],
    })
    endpoint_id = _upsert_rpc_endpoint(cursor, chain_id, failed_probe, selected=False)
    cursor.execute(
        "UPDATE rpc_endpoints SET is_enabled = true, is_selected = false, healthy = false, last_error = %s, latency_ms = %s, last_checked_at = now(), updated_at = now() WHERE id = %s",
        (reason[:80], response_seconds_to_latency_ms(probe.response_seconds), endpoint_id),
    )
    _insert_rpc_endpoint_check(cursor, endpoint_id, chain_id, failed_probe, None)
    return endpoint_id, current_id == endpoint_id

def _current_selected_endpoint_id(cursor, chain_id: str) -> int | None:
    cursor.execute("SELECT id FROM rpc_endpoints WHERE chain_id = %s AND is_selected", (chain_id,))
    row = cursor.fetchone()
    return int(row[0]) if row else None


def _upsert_rpc_endpoint(cursor, chain_id: str, probe: RpcProbeResult, selected: bool) -> int:
    cursor.execute("SELECT chain_id FROM rpc_endpoints WHERE url = %s", (probe.url,))
    existing = cursor.fetchone()
    if existing and existing[0] != chain_id:
        raise ChainIdentityError(f"Existing RPC URL {probe.url} belongs to chain_id={existing[0]}, not {chain_id}")
    cursor.execute(
        """
        INSERT INTO rpc_endpoints(
            url, chain_id, is_selected, last_checked_at, latest_observed_height,
            observed_lag, catching_up, healthy, last_error, latency_ms
        )
        VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET
            is_enabled = true,
            last_checked_at = now(),
            latest_observed_height = EXCLUDED.latest_observed_height,
            observed_lag = EXCLUDED.observed_lag,
            catching_up = EXCLUDED.catching_up,
            healthy = EXCLUDED.healthy,
            last_error = EXCLUDED.last_error,
            latency_ms = EXCLUDED.latency_ms,
            updated_at = now()
        RETURNING id
        """,
        (probe.url, chain_id, selected, probe.latest_height, probe.observed_lag, probe.catching_up, probe.healthy, probe.error_message, response_seconds_to_latency_ms(probe.response_seconds)),
    )
    return int(cursor.fetchone()[0])


def _mark_rpc_endpoint_selected(cursor, endpoint_id: int, probe: RpcProbeResult) -> None:
    cursor.execute(
        """
        UPDATE rpc_endpoints
        SET is_selected = true,
            last_selected_at = now(),
            latest_observed_height = %s,
            observed_lag = %s,
            catching_up = %s,
            healthy = %s,
            last_error = %s,
            latency_ms = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (probe.latest_height, probe.observed_lag, probe.catching_up, probe.healthy, probe.error_message, response_seconds_to_latency_ms(probe.response_seconds), endpoint_id),
    )


def response_seconds_to_latency_ms(value: object) -> int | None:
    """Convert a measured duration to the bounded current-snapshot value."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(math.floor(seconds * 1000 + 0.5), 30000)


def _insert_rpc_endpoint_check(cursor, endpoint_id: int, chain_id: str, probe: RpcProbeResult, switch_reason: str | None) -> None:
    cursor.execute(
        """
        INSERT INTO rpc_endpoint_checks(
            rpc_endpoint_id, chain_id, latest_observed_height, observed_lag, catching_up,
            healthy, selected_for_cycle, switch_reason, error_message
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (endpoint_id, chain_id, probe.latest_height, probe.observed_lag, probe.catching_up, probe.healthy, probe.selected, switch_reason, probe.error_message),
    )


def write_height_cursor(cursor, parsed, chain_id: str, finalized_tip: int, selected_rpc_endpoint_id: int | None) -> None:
    checkpoint = get_checkpoint_cursor(cursor, chain_id)
    _verify_checkpoint_sequence(parsed.height, checkpoint)
    lock_realm_call_index(cursor)
    _verify_finalized_conflicts(cursor, parsed)
    _upsert_block(cursor, parsed)
    _upsert_transactions(cursor, parsed, selected_rpc_endpoint_id)
    _replace_realm_calls_for_height(cursor, parsed, chain_id)
    _upsert_realm_catalog(cursor, parsed, chain_id)
    advance_realm_call_coverage(
        cursor, chain_id, parsed.height, initialize_if_missing=checkpoint is None
    )
    advance_realm_activity_coverage(cursor, chain_id, parsed.height)
    _upsert_validators_and_members(cursor, parsed)
    _upsert_signatures(cursor, parsed)
    _advance_checkpoint(cursor, parsed.height, checkpoint, chain_id, finalized_tip, selected_rpc_endpoint_id)


def advance_realm_activity_coverage(cursor, chain_id: str, height: int) -> RealmActivityCoverageResult:
    """Advance an initialized Realm activity range by exactly one block."""
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise ValueError("chain_id must be a non-empty string")
    if isinstance(height, bool) or not isinstance(height, int) or height < 1:
        raise ValueError("height must be a positive integer")
    cursor.execute(
        "SELECT activity_from_height, activity_through_height "
        "FROM realm_catalog_state WHERE chain_id = %s FOR UPDATE",
        (chain_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return RealmActivityCoverageResult(None, None, False)
    activity_from, previous = row
    if activity_from is None and previous is None:
        return RealmActivityCoverageResult(None, None, False)
    if activity_from is None or previous is None:
        raise RealmActivityCoverageError(f"Incompatible Realm activity coverage state for chain {chain_id}")
    previous = int(previous)
    if height <= previous:
        return RealmActivityCoverageResult(previous, previous, False)
    if height != previous + 1:
        raise RealmActivityCoverageError(
            f"Realm activity coverage for chain {chain_id} cannot advance from "
            f"{previous} through {height}; a full Realm activity rebuild is required"
        )
    cursor.execute(
        "UPDATE realm_catalog_state SET activity_through_height = %s, updated_at = now() "
        "WHERE chain_id = %s",
        (height, chain_id),
    )
    return RealmActivityCoverageResult(previous, height, True)


def lock_realm_call_index(cursor) -> None:
    """Serialize live writes and rebuilds for the transaction lifetime."""
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (REALM_CALL_INDEX_LOCK_ID,))


def advance_realm_call_coverage(
    cursor, chain_id: str, height: int, *, initialize_if_missing: bool = False
) -> RealmCallCoverageResult:
    """Initialize truthful fresh coverage or advance existing coverage exactly."""
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise ValueError("chain_id must be a non-empty string")
    if isinstance(height, bool) or not isinstance(height, int) or height < 1:
        raise ValueError("height must be a positive integer")
    cursor.execute(
        "SELECT from_height, through_height FROM realm_call_index_state "
        "WHERE chain_id = %s FOR UPDATE", (chain_id,),
    )
    row = cursor.fetchone()
    if row is None:
        if initialize_if_missing:
            cursor.execute(
                "INSERT INTO realm_call_index_state(chain_id, from_height, through_height) "
                "VALUES (%s, %s, %s)",
                (chain_id, height, height),
            )
            if cursor.rowcount != 1:
                raise RealmCallCoverageError(
                    "Realm call coverage initialization did not affect exactly one row"
                )
            return RealmCallCoverageResult(None, height, True)
        return RealmCallCoverageResult(None, None, False)
    if len(row) != 2 or row[0] is None or row[1] is None:
        raise RealmCallCoverageError(f"Incompatible Realm call coverage state for chain {chain_id}")
    previous = int(row[1])
    if height <= previous:
        return RealmCallCoverageResult(previous, previous, False)
    if height != previous + 1:
        raise RealmCallCoverageError(
            f"Realm call coverage for chain {chain_id} cannot advance from "
            f"{previous} through {height}; a rebuild is required"
        )
    cursor.execute(
        "UPDATE realm_call_index_state SET through_height=%s, updated_at=now() "
        "WHERE chain_id=%s", (height, chain_id),
    )
    if cursor.rowcount != 1:
        raise RealmCallCoverageError("Realm call coverage update did not affect exactly one row")
    return RealmCallCoverageResult(previous, height, True)


def _verify_checkpoint_sequence(height: int, checkpoint: int | None) -> None:
    if checkpoint is not None and height > checkpoint + 1:
        raise DatabaseError(f"Refusing to skip from checkpoint {checkpoint} to height {height}")


def _advance_checkpoint(cursor, height: int, checkpoint: int | None, chain_id: str, finalized_tip: int, endpoint_id: int | None) -> None:
    if checkpoint is not None and height <= checkpoint:
        return
    if checkpoint is not None and height != checkpoint + 1:
        raise DatabaseError(f"Height {height} is not the next sequential checkpoint after {checkpoint}")
    cursor.execute(
        """
        INSERT INTO indexer_state(state_key, chain_id, last_finalized_height, finalized_tip_height, selected_rpc_endpoint_id)
        VALUES ('default', %s, %s, %s, %s)
        ON CONFLICT (state_key) DO UPDATE SET
            last_finalized_height = GREATEST(indexer_state.last_finalized_height, EXCLUDED.last_finalized_height),
            finalized_tip_height = EXCLUDED.finalized_tip_height,
            selected_rpc_endpoint_id = EXCLUDED.selected_rpc_endpoint_id,
            updated_at = now()
        """,
        (chain_id, height, finalized_tip, endpoint_id),
    )


def _verify_finalized_conflicts(cursor, parsed) -> None:
    existing_height = _verify_block_conflict(cursor, parsed)
    _verify_child_key_sets(cursor, parsed, existing_height)
    _verify_transaction_conflicts(cursor, parsed)
    _verify_execution_result_conflicts(cursor, parsed)
    _verify_validator_conflicts(cursor, parsed)
    _verify_member_conflicts(cursor, parsed)
    _verify_signature_conflicts(cursor, parsed)


def _verify_block_conflict(cursor, parsed) -> bool:
    cursor.execute("SELECT block_hash_base64, block_hash_hex FROM blocks WHERE height = %s", (parsed.height,))
    row = cursor.fetchone()
    if row and (row[0] != parsed.block["hash_base64"] or row[1] != parsed.block["hash_hex"]):
        raise FinalizedDataConflict(f"Conflicting finalized block hash at height {parsed.height}")
    return row is not None


def _verify_child_key_sets(cursor, parsed, existing_height: bool) -> None:
    if not existing_height:
        return
    incoming_tx_indexes = {transaction["index"] for transaction in parsed.transactions}
    existing_tx_indexes = _fetch_single_column_set(cursor, "SELECT tx_index FROM transactions WHERE block_height = %s", (parsed.height,))
    if existing_tx_indexes != incoming_tx_indexes:
        raise FinalizedDataConflict(f"Conflicting transaction index set at height {parsed.height}")

    incoming_members = {validator["address"] for validator in parsed.validators}
    existing_members = _fetch_single_column_set(cursor, "SELECT signing_address FROM validator_set_members WHERE height = %s", (parsed.height,))
    if existing_members != incoming_members:
        raise FinalizedDataConflict(f"Conflicting validator-set member set at height {parsed.height}")

    incoming_signatures = {signature["signing_address"] for signature in parsed.signatures}
    existing_signatures = _fetch_single_column_set(cursor, "SELECT signing_address FROM validator_signatures WHERE height = %s", (parsed.height,))
    if existing_signatures != incoming_signatures:
        raise FinalizedDataConflict(f"Conflicting validator signature set at height {parsed.height}")


def _fetch_single_column_set(cursor, sql: str, params: tuple[Any, ...]) -> set[Any]:
    cursor.execute(sql, params)
    return {row[0] for row in cursor.fetchall()}


def _verify_transaction_conflicts(cursor, parsed) -> None:
    for transaction in parsed.transactions:
        cursor.execute(
            "SELECT raw_base64, raw_base64_length, decoded_byte_length, decode_status, tx_hash_hex FROM transactions WHERE block_height = %s AND tx_index = %s",
            (parsed.height, transaction["index"]),
        )
        row = cursor.fetchone()
        expected = (transaction["raw_base64"], transaction["raw_base64_length"], transaction["decoded_byte_length"], transaction["decode_status"], transaction["tx_hash_hex"])
        if row and tuple(row) != expected:
            raise FinalizedDataConflict(f"Conflicting transaction at height {parsed.height} index {transaction['index']}")


def _verify_execution_result_conflicts(cursor, parsed) -> None:
    for result in getattr(parsed, "execution_results", []):
        cursor.execute(
            "SELECT execution_status, gas_wanted, gas_used, error_text, log_text, info_text, data_base64, events, raw_result FROM transaction_execution_results WHERE block_height = %s AND tx_index = %s",
            (parsed.height, result["tx_index"]),
        )
        row = cursor.fetchone()
        expected = (result["execution_status"], result["gas_wanted"], result["gas_used"], result["error_text"], result["log_text"], result["info_text"], result["data_base64"], result["events"], result["raw_result"])
        if row and tuple(row) != expected:
            raise FinalizedDataConflict(f"Conflicting execution result at height {parsed.height} index {result['tx_index']}")


def _verify_validator_conflicts(cursor, parsed) -> None:
    for validator in parsed.validators:
        cursor.execute("SELECT public_key_type, public_key_value FROM validators WHERE signing_address = %s", (validator["address"],))
        row = cursor.fetchone()
        expected = (validator.get("pub_key_type") or "unknown", validator.get("pub_key_value") or "")
        if row and tuple(row) != expected:
            raise FinalizedDataConflict(f"Conflicting validator identity for {validator['address']}")


def _verify_member_conflicts(cursor, parsed) -> None:
    for validator_index, validator in enumerate(parsed.validators):
        cursor.execute(
            "SELECT voting_power, proposer_priority, validator_index FROM validator_set_members WHERE height = %s AND signing_address = %s",
            (parsed.height, validator["address"]),
        )
        row = cursor.fetchone()
        expected = (validator.get("voting_power") or 0, validator.get("proposer_priority"), validator_index)
        if row and tuple(row) != expected:
            raise FinalizedDataConflict(f"Conflicting validator-set member at height {parsed.height} for {validator['address']}")


def _verify_signature_conflicts(cursor, parsed) -> None:
    for signature in parsed.signatures:
        cursor.execute(
            "SELECT vote_status, signed, vote_block_id_hash_base64, vote_block_id_hash_hex, vote_block_id_parts_total, vote_block_id_parts_hash_base64, vote_block_id_parts_hash_hex, vote_block_id_is_zero, block_id_matches_commit, signature_base64 FROM validator_signatures WHERE height = %s AND signing_address = %s",
            (parsed.height, signature["signing_address"]),
        )
        row = cursor.fetchone()
        expected = (
            signature["vote_status"],
            signature["signed"],
            signature["vote_block_id_hash_base64"],
            signature["vote_block_id_hash_hex"],
            signature["vote_block_id_parts_total"],
            signature["vote_block_id_parts_hash_base64"],
            signature["vote_block_id_parts_hash_hex"],
            signature["vote_block_id_is_zero"],
            signature["block_id_matches_commit"],
            signature["signature_base64"],
        )
        if row and tuple(row) != expected:
            raise FinalizedDataConflict(f"Conflicting validator signature at height {parsed.height} for {signature['signing_address']}")


def _upsert_block(cursor, parsed) -> None:
    block = parsed.block
    cursor.execute(
        """
        INSERT INTO blocks(height, block_hash_base64, block_hash_hex, time_utc, proposer_address, tx_count, raw_block_response)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (height) DO UPDATE SET updated_at = now()
        """,
        (parsed.height, block["hash_base64"], block["hash_hex"], block["time"], block["proposer_address"], block["tx_count"], _json(parsed.raw_block)),
    )


def _upsert_transactions(cursor, parsed, selected_rpc_endpoint_id: int | None = None) -> None:
    for transaction in parsed.transactions:
        fallback_status = "invalid" if transaction["decode_status"] == "invalid_base64" else "unparsed"
        payload_summary = normalize_summary(transaction.get("payload_summary"), fallback_status)
        cursor.execute(
            """
            INSERT INTO transactions(block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex, payload_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (block_height, tx_index) DO UPDATE SET
                payload_summary = EXCLUDED.payload_summary
            """,
            (parsed.height, transaction["index"], transaction["raw_base64"], transaction["raw_base64_length"], transaction["decoded_bytes"], transaction["decoded_byte_length"], transaction["decode_status"], transaction["tx_hash_hex"], _json(payload_summary)),
        )
        cursor.execute(
            "DELETE FROM transaction_participants WHERE block_height = %s AND tx_index = %s",
            (parsed.height, transaction["index"]),
        )
        participants = extract_transaction_participants(payload_summary)
        if participants:
            cursor.executemany(
                """
                INSERT INTO transaction_participants(block_height, tx_index, message_index, role, address)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [
                    (parsed.height, transaction["index"], participant.message_index,
                     participant.role, participant.address)
                    for participant in participants
                ],
            )
    for result in getattr(parsed, "execution_results", []):
        cursor.execute(
            """
            INSERT INTO transaction_execution_results(
                block_height, tx_index, execution_status, gas_wanted, gas_used,
                error_text, log_text, info_text, data_base64, events, raw_result,
                source_rpc_endpoint_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            ON CONFLICT (block_height, tx_index) DO UPDATE SET updated_at = now()
            """,
            (parsed.height, result["tx_index"], result["execution_status"],
             result["gas_wanted"], result["gas_used"], result["error_text"],
             result["log_text"], result["info_text"], result["data_base64"],
             _json(result["events"]), _json(result["raw_result"]),
             selected_rpc_endpoint_id),
        )


def _upsert_realm_catalog(cursor, parsed, chain_id: str) -> None:
    """Write at most one derived catalog row per touched path and height."""
    statuses = {result["tx_index"]: result["execution_status"]
                for result in getattr(parsed, "execution_results", [])}
    summaries = []
    for transaction in parsed.transactions:
        fallback = "invalid" if transaction["decode_status"] == "invalid_base64" else "unparsed"
        summaries.append((transaction["index"], normalize_summary(transaction.get("payload_summary"), fallback),
                          statuses.get(transaction["index"])))
    upsert_transaction_catalog_aggregates(
        cursor, chain_id, parsed.height, parsed.block["time"], aggregate_block(summaries)
    )


def _replace_realm_calls_for_height(cursor, parsed, chain_id: str) -> int:
    """Exactly replace compact call locators for one finalized height."""
    cursor.execute(
        "DELETE FROM realm_call_index WHERE chain_id = %s AND block_height = %s",
        (chain_id, parsed.height),
    )
    positions: set[tuple[int, int]] = set()
    inserted = 0
    for transaction in parsed.transactions:
        fallback = "invalid" if transaction["decode_status"] == "invalid_base64" else "unparsed"
        summary = normalize_summary(transaction.get("payload_summary"), fallback)
        for call in extract_realm_calls(summary):
            position = (transaction["index"], call.message_index)
            if position in positions:
                raise DatabaseError("Duplicate Realm call position in finalized height")
            positions.add(position)
            cursor.execute("""
                INSERT INTO realm_call_index(
                    chain_id,block_height,tx_index,message_index,path,caller_address,
                    function_name,args_count,send_amount)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (chain_id, parsed.height, transaction["index"], call.message_index,
                  call.path, call.caller_address, call.function_name,
                  call.args_count, call.send_amount))
            if cursor.rowcount != 1:
                raise DatabaseError("Realm call insert did not affect exactly one row")
            inserted += 1
    if inserted != len(positions):
        raise DatabaseError("Realm call replacement count mismatch")
    return inserted


def upsert_transaction_catalog_aggregates(
    cursor, chain_id: str, height: int, block_time: Any, aggregates
) -> None:
    """Upsert bounded transaction-derived aggregates for exactly one block height."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 1:
        raise ValueError("height must be positive")
    for aggregate in aggregates:
        cursor.execute("""
            INSERT INTO realm_catalog(
                chain_id,path,path_kind,seen_via_transactions,deployer_address,deploy_height,
                deploy_tx_index,first_seen_height,last_activity_height,last_activity_tx_index,
                last_activity_at,call_count,successful_call_count,failed_call_count,
                unknown_result_call_count,last_counted_height)
            VALUES (%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (chain_id,path) DO UPDATE SET
                path_kind=EXCLUDED.path_kind, seen_via_transactions=true,
                first_seen_height=LEAST(realm_catalog.first_seen_height,EXCLUDED.first_seen_height),
                deployer_address=CASE WHEN realm_catalog.deploy_height IS NULL OR
                    (EXCLUDED.deploy_height,EXCLUDED.deploy_tx_index) < (realm_catalog.deploy_height,realm_catalog.deploy_tx_index)
                    THEN EXCLUDED.deployer_address ELSE realm_catalog.deployer_address END,
                deploy_height=CASE WHEN realm_catalog.deploy_height IS NULL OR
                    (EXCLUDED.deploy_height,EXCLUDED.deploy_tx_index) < (realm_catalog.deploy_height,realm_catalog.deploy_tx_index)
                    THEN EXCLUDED.deploy_height ELSE realm_catalog.deploy_height END,
                deploy_tx_index=CASE WHEN realm_catalog.deploy_height IS NULL OR
                    (EXCLUDED.deploy_height,EXCLUDED.deploy_tx_index) < (realm_catalog.deploy_height,realm_catalog.deploy_tx_index)
                    THEN EXCLUDED.deploy_tx_index ELSE realm_catalog.deploy_tx_index END,
                last_activity_height=CASE WHEN EXCLUDED.last_activity_height IS NOT NULL AND
                    (realm_catalog.last_activity_height IS NULL OR (EXCLUDED.last_activity_height,EXCLUDED.last_activity_tx_index) >
                    (realm_catalog.last_activity_height,realm_catalog.last_activity_tx_index)) THEN EXCLUDED.last_activity_height ELSE realm_catalog.last_activity_height END,
                last_activity_tx_index=CASE WHEN EXCLUDED.last_activity_height IS NOT NULL AND
                    (realm_catalog.last_activity_height IS NULL OR (EXCLUDED.last_activity_height,EXCLUDED.last_activity_tx_index) >
                    (realm_catalog.last_activity_height,realm_catalog.last_activity_tx_index)) THEN EXCLUDED.last_activity_tx_index ELSE realm_catalog.last_activity_tx_index END,
                last_activity_at=CASE WHEN EXCLUDED.last_activity_height IS NOT NULL AND
                    (realm_catalog.last_activity_height IS NULL OR EXCLUDED.last_activity_height >= realm_catalog.last_activity_height)
                    THEN EXCLUDED.last_activity_at ELSE realm_catalog.last_activity_at END,
                call_count=realm_catalog.call_count + CASE WHEN EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0) THEN EXCLUDED.call_count ELSE 0 END,
                successful_call_count=realm_catalog.successful_call_count + CASE WHEN EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0) THEN EXCLUDED.successful_call_count ELSE 0 END,
                failed_call_count=realm_catalog.failed_call_count + CASE WHEN EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0) THEN EXCLUDED.failed_call_count ELSE 0 END,
                unknown_result_call_count=realm_catalog.unknown_result_call_count + CASE WHEN EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0) THEN EXCLUDED.unknown_result_call_count ELSE 0 END,
                last_counted_height=CASE WHEN EXCLUDED.last_counted_height > COALESCE(realm_catalog.last_counted_height,0) THEN EXCLUDED.last_counted_height ELSE realm_catalog.last_counted_height END,
                updated_at=now()
        """, (chain_id, aggregate.path, aggregate.kind, aggregate.deployer_address,
              height if aggregate.deploy_tx_index is not None else None, aggregate.deploy_tx_index,
              height, height if aggregate.call_count else None, aggregate.last_activity_tx_index,
              block_time if aggregate.call_count else None, aggregate.call_count,
              aggregate.successful_call_count, aggregate.failed_call_count, aggregate.unknown_result_call_count,
              height if aggregate.call_count else None))


def _upsert_validators_and_members(cursor, parsed) -> None:
    for index, validator in enumerate(parsed.validators):
        cursor.execute(
            """
            INSERT INTO validators(signing_address, public_key_type, public_key_value, first_seen_height, last_seen_height)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (signing_address) DO UPDATE SET
                first_seen_height = LEAST(validators.first_seen_height, EXCLUDED.first_seen_height),
                last_seen_height = GREATEST(validators.last_seen_height, EXCLUDED.last_seen_height),
                updated_at = now()
            """,
            (validator["address"], validator.get("pub_key_type") or "unknown", validator.get("pub_key_value") or "", parsed.height, parsed.height),
        )
        cursor.execute(
            """
            INSERT INTO validator_set_members(height, signing_address, voting_power, proposer_priority, validator_index, raw_validator)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (height, signing_address) DO NOTHING
            """,
            (parsed.height, validator["address"], validator.get("voting_power") or 0, validator.get("proposer_priority"), index, _json(validator)),
        )


def _upsert_signatures(cursor, parsed) -> None:
    for signature in parsed.signatures:
        cursor.execute(
            """
            INSERT INTO validator_signatures(
                height, signing_address, vote_status, signed, vote_block_id_hash_base64,
                vote_block_id_hash_hex, vote_block_id_parts_total, vote_block_id_parts_hash_base64,
                vote_block_id_parts_hash_hex, vote_block_id_is_zero, block_id_matches_commit,
                signature_base64, raw_precommit
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (height, signing_address) DO NOTHING
            """,
            (
                parsed.height,
                signature["signing_address"],
                signature["vote_status"],
                signature["signed"],
                signature["vote_block_id_hash_base64"],
                signature["vote_block_id_hash_hex"],
                signature["vote_block_id_parts_total"],
                signature["vote_block_id_parts_hash_base64"],
                signature["vote_block_id_parts_hash_hex"],
                signature["vote_block_id_is_zero"],
                signature["block_id_matches_commit"],
                signature["signature_base64"],
                _json(signature["raw_precommit"]),
            ),
        )


def _json(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None
