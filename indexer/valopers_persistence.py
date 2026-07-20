"""Atomic PostgreSQL persistence for the current complete Valopers snapshot."""
from __future__ import annotations

from dataclasses import dataclass

from .valopers_parser import ValoperProfile
from .valopers_snapshot import MAX_VALOPERS_PAGES, MAX_VALOPERS_PROFILES, ValopersSnapshot

# Dedicated signed BIGINT namespace for the transaction-scoped Valopers writer lock.
VALOPERS_WRITER_ADVISORY_LOCK_KEY = 824312905617430211


class ValopersPersistenceError(RuntimeError):
    """Base error for bounded Valopers snapshot persistence failures."""


class ValopersChainIdentityError(ValopersPersistenceError):
    """Raised when stored and configured chain identities differ."""


class StaleValopersSnapshot(ValopersPersistenceError):
    """Raised when an incoming snapshot predates the stored snapshot."""


class ValopersSnapshotConflict(ValopersPersistenceError):
    """Raised for divergent snapshots at the same chain height."""


class ValopersStoredStateError(ValopersPersistenceError):
    """Raised when the persisted state is internally inconsistent."""


@dataclass(frozen=True)
class ValopersPersistenceResult:
    action: str
    source_height: int
    page_count: int
    profile_count: int


def _profile_tuple(profile: ValoperProfile) -> tuple[str, ...]:
    return (
        profile.operator_address, profile.moniker, profile.description,
        profile.server_type, profile.signing_address, profile.signing_pubkey,
    )


def validate_valopers_snapshot(snapshot: ValopersSnapshot, chain_id: str) -> tuple[tuple[str, ...], ...]:
    """Validate bounded metadata and identities without mutating caller data."""
    if not isinstance(snapshot, ValopersSnapshot):
        raise ValopersPersistenceError("snapshot must be a ValopersSnapshot")
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise ValopersPersistenceError("chain_id must be a non-empty string")
    if (not isinstance(snapshot.source_height, int) or isinstance(snapshot.source_height, bool)
            or snapshot.source_height < 1):
        raise ValopersPersistenceError("source_height must be a positive integer")
    if (not isinstance(snapshot.page_count, int) or isinstance(snapshot.page_count, bool)
            or not 0 <= snapshot.page_count <= MAX_VALOPERS_PAGES):
        raise ValopersPersistenceError("page_count is outside the supported bounds")
    if not isinstance(snapshot.profiles, tuple) or len(snapshot.profiles) > MAX_VALOPERS_PROFILES:
        raise ValopersPersistenceError("profiles must be a bounded tuple")
    if (not snapshot.profiles and snapshot.page_count != 0) or (snapshot.profiles and snapshot.page_count < 1):
        raise ValopersPersistenceError("profile and page counts are inconsistent")
    if any(not isinstance(profile, ValoperProfile) for profile in snapshot.profiles):
        raise ValopersPersistenceError("profiles must contain ValoperProfile values")
    rows = tuple(_profile_tuple(profile) for profile in snapshot.profiles)
    for index in (0, 4, 5):
        values = [row[index] for row in rows]
        if len(values) != len(set(values)):
            raise ValopersPersistenceError("Valoper identities must be unique")
    return rows


def replace_valopers_snapshot_cursor(cursor, snapshot: ValopersSnapshot, chain_id: str) -> ValopersPersistenceResult:
    """Validate and replace a snapshot using the cursor's existing transaction."""
    incoming = validate_valopers_snapshot(snapshot, chain_id)
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (VALOPERS_WRITER_ADVISORY_LOCK_KEY,))
    cursor.execute("SELECT chain_id FROM indexer_state WHERE state_key = %s", ("default",))
    indexer_state = cursor.fetchone()
    if indexer_state is not None:
        indexed_chain_id = indexer_state[0]
        if (not isinstance(indexed_chain_id, str) or not indexed_chain_id.strip()
                or indexed_chain_id != chain_id):
            raise ValopersChainIdentityError("indexer state belongs to another chain")
    cursor.execute(
        "SELECT state_key, chain_id, source_height, page_count, profile_count "
        "FROM valopers_snapshot_state WHERE state_key = %s FOR UPDATE", ("default",)
    )
    state = cursor.fetchone()
    cursor.execute(
        "SELECT operator_address, moniker, description, server_type, signing_address, "
        "signing_pubkey, source_height, list_position FROM valoper_profiles ORDER BY list_position"
    )
    stored_rows = [tuple(row) for row in cursor.fetchall()]
    _validate_stored_state(state, stored_rows)

    if state is not None:
        _, stored_chain, stored_height, stored_pages, stored_count = state
        if stored_chain != chain_id:
            raise ValopersChainIdentityError("stored snapshot belongs to another chain")
        if snapshot.source_height < stored_height:
            raise StaleValopersSnapshot("incoming snapshot is stale")
        if snapshot.source_height == stored_height:
            stored_profiles = tuple(row[:6] for row in stored_rows)
            if (snapshot.page_count, len(incoming), incoming) == (stored_pages, stored_count, stored_profiles):
                return ValopersPersistenceResult("unchanged", snapshot.source_height, snapshot.page_count, len(incoming))
            raise ValopersSnapshotConflict("same-height Valopers snapshots differ")

    cursor.execute("DELETE FROM valoper_profiles")
    for position, row in enumerate(incoming):
        cursor.execute(
            "INSERT INTO valoper_profiles (operator_address, moniker, description, server_type, "
            "signing_address, signing_pubkey, source_height, list_position) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (*row, snapshot.source_height, position),
        )
    cursor.execute(
        "INSERT INTO valopers_snapshot_state (state_key, chain_id, source_height, page_count, profile_count) "
        "VALUES ('default', %s, %s, %s, %s) ON CONFLICT (state_key) DO UPDATE SET "
        "chain_id = EXCLUDED.chain_id, source_height = EXCLUDED.source_height, "
        "page_count = EXCLUDED.page_count, profile_count = EXCLUDED.profile_count, updated_at = now()",
        (chain_id, snapshot.source_height, snapshot.page_count, len(incoming)),
    )
    _verify_written_snapshot(cursor, snapshot, chain_id, incoming)
    return ValopersPersistenceResult("applied", snapshot.source_height, snapshot.page_count, len(incoming))


def _validate_stored_state(state, rows: list[tuple]) -> None:
    if state is None:
        if rows:
            raise ValopersStoredStateError("profiles exist without snapshot state")
        return
    key, chain_id, height, pages, count = state
    valid_metadata = (
        key == "default" and isinstance(chain_id, str) and bool(chain_id.strip())
        and isinstance(height, int) and height >= 1
        and isinstance(pages, int) and 0 <= pages <= MAX_VALOPERS_PAGES
        and isinstance(count, int) and 0 <= count <= MAX_VALOPERS_PROFILES
        and ((count == 0 and pages == 0) or (count > 0 and pages >= 1))
    )
    positions = [row[7] for row in rows]
    if (not valid_metadata or len(rows) != count
            or any(row[6] != height for row in rows)
            or positions != list(range(count))):
        raise ValopersStoredStateError("stored Valopers snapshot is inconsistent")


def _verify_written_snapshot(cursor, snapshot, chain_id: str, incoming: tuple[tuple[str, ...], ...]) -> None:
    cursor.execute(
        "SELECT state_key, chain_id, source_height, page_count, profile_count "
        "FROM valopers_snapshot_state WHERE state_key = %s", ("default",)
    )
    expected_state = ("default", chain_id, snapshot.source_height, snapshot.page_count, len(incoming))
    if cursor.fetchone() != expected_state:
        raise ValopersPersistenceError("written snapshot state verification failed")
    cursor.execute(
        "SELECT operator_address, moniker, description, server_type, signing_address, signing_pubkey, "
        "source_height, list_position FROM valoper_profiles ORDER BY list_position"
    )
    expected_rows = [(*row, snapshot.source_height, position) for position, row in enumerate(incoming)]
    if [tuple(row) for row in cursor.fetchall()] != expected_rows:
        raise ValopersPersistenceError("written snapshot profile verification failed")
