"""PostgreSQL writes for the bounded indexer."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .rpc import RpcProbeResult
from .valopers_persistence import ValopersPersistenceResult, replace_valopers_snapshot_cursor
from .valopers_snapshot import ValopersSnapshot


class DatabaseError(RuntimeError):
    """Raised for database configuration or write failures."""


class FinalizedDataConflict(DatabaseError):
    """Raised when existing finalized data conflicts with reprocessed RPC data."""


class ChainIdentityError(DatabaseError):
    """Raised when persisted chain identity does not match runtime configuration."""


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

    def record_rpc_probe_cycle(self, chain_id: str, probes: list[RpcProbeResult]) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.selected_rpc_endpoint_id = record_rpc_probe_cycle_cursor(cursor, chain_id, probes)
            connection.commit()

    def select_rpc_endpoint(self, chain_id: str, probe: RpcProbeResult, reason: str) -> None:
        with self.connect() as connection, connection.cursor() as cursor:
            self.selected_rpc_endpoint_id = select_rpc_endpoint_cursor(cursor, chain_id, probe, reason)
        connection.commit()

    def record_rpc_runtime_failure(self, chain_id: str, probe: RpcProbeResult, reason: str) -> None:
        with self.connect() as connection, connection.cursor() as cursor:
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
        "UPDATE rpc_endpoints SET is_enabled = true, is_selected = false, healthy = false, last_error = %s, last_checked_at = now(), updated_at = now() WHERE id = %s",
        (reason[:80], endpoint_id),
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
            observed_lag, catching_up, healthy, last_error
        )
        VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET
            is_enabled = true,
            last_checked_at = now(),
            latest_observed_height = EXCLUDED.latest_observed_height,
            observed_lag = EXCLUDED.observed_lag,
            catching_up = EXCLUDED.catching_up,
            healthy = EXCLUDED.healthy,
            last_error = EXCLUDED.last_error,
            updated_at = now()
        RETURNING id
        """,
        (probe.url, chain_id, selected, probe.latest_height, probe.observed_lag, probe.catching_up, probe.healthy, probe.error_message),
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
            updated_at = now()
        WHERE id = %s
        """,
        (probe.latest_height, probe.observed_lag, probe.catching_up, probe.healthy, probe.error_message, endpoint_id),
    )


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
    _verify_finalized_conflicts(cursor, parsed)
    _upsert_block(cursor, parsed)
    _upsert_transactions(cursor, parsed)
    _upsert_validators_and_members(cursor, parsed)
    _upsert_signatures(cursor, parsed)
    _advance_checkpoint(cursor, parsed.height, checkpoint, chain_id, finalized_tip, selected_rpc_endpoint_id)


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


def _upsert_transactions(cursor, parsed) -> None:
    for transaction in parsed.transactions:
        cursor.execute(
            """
            INSERT INTO transactions(block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (block_height, tx_index) DO NOTHING
            """,
            (parsed.height, transaction["index"], transaction["raw_base64"], transaction["raw_base64_length"], transaction["decoded_bytes"], transaction["decoded_byte_length"], transaction["decode_status"], transaction["tx_hash_hex"]),
        )


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
