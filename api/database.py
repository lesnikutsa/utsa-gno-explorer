"""Database pool and read-only query helpers for the API."""

from datetime import datetime, timezone
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
    ) AS rpc_last_checked_at,
    EXISTS (
        SELECT 1
        FROM rpc_endpoints healthy_rpc
        WHERE healthy_rpc.chain_id = s.chain_id
          AND healthy_rpc.is_enabled = %s
          AND healthy_rpc.healthy = %s
    ) AS has_healthy_rpc
FROM indexer_state s
WHERE s.state_key = %s
"""

NETWORK_SQL = """
SELECT
    s.chain_id,
    s.last_finalized_height AS indexed_height,
    s.finalized_tip_height,
    b.height AS block_height,
    b.block_hash_hex,
    b.time_utc,
    b.proposer_address,
    profile.moniker AS proposer_moniker,
    b.tx_count,
    COALESCE(v.active_count, 0) AS validator_active_count,
    COALESCE(v.total_voting_power, 0)::text AS validator_total_voting_power,
    block_time.average_block_time_seconds,
    block_time.average_block_time_sample_size,
    r.url AS rpc_url,
    r.healthy AS rpc_healthy,
    r.catching_up AS rpc_catching_up,
    r.latest_observed_height AS rpc_observed_height,
    r.observed_lag AS rpc_lag,
    r.last_checked_at AS rpc_last_checked_at
FROM indexer_state s
JOIN blocks b ON b.height = s.last_finalized_height
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = b.proposer_address
LEFT JOIN LATERAL (
    SELECT count(*)::bigint AS active_count, COALESCE(sum(vsm.voting_power), 0) AS total_voting_power
    FROM validator_set_members vsm
    WHERE vsm.height = s.last_finalized_height
) v ON true
LEFT JOIN LATERAL (
    SELECT
        sample_size AS average_block_time_sample_size,
        CASE
            WHEN sample_size >= 2
             AND maximum_height - minimum_height + 1 = sample_size
             AND ending_time IS NOT NULL
             AND starting_time IS NOT NULL
             AND ending_time > starting_time
            THEN EXTRACT(EPOCH FROM (ending_time - starting_time)) / (sample_size - 1)
            ELSE NULL
        END AS average_block_time_seconds
    FROM (
        SELECT
            count(*)::bigint AS sample_size,
            min(height) AS minimum_height,
            max(height) AS maximum_height,
            (array_agg(time_utc ORDER BY height ASC))[1] AS starting_time,
            (array_agg(time_utc ORDER BY height DESC))[1] AS ending_time
        FROM (
            SELECT height, time_utc
            FROM blocks
            WHERE height <= s.last_finalized_height
            ORDER BY height DESC
            LIMIT 10
        ) bounded_blocks
    ) sampled_blocks
) block_time ON true
LEFT JOIN rpc_endpoints r ON r.id = s.selected_rpc_endpoint_id
WHERE s.state_key = %s
"""

NETWORK_DISTRIBUTION_SQL = """
SELECT
    state.chain_id,
    snapshot.source_kind,
    snapshot.scanned_at,
    snapshot.rpc_sources_total,
    snapshot.rpc_sources_ok,
    snapshot.visible_node_ids,
    snapshot.unique_public_ips,
    snapshot.geolocated_node_ids,
    snapshot.geolocated_public_ips,
    snapshot.node_id_ip_conflicts,
    snapshot.region_count,
    snapshot.country_count,
    snapshot.provider_count,
    snapshot.regions,
    snapshot.countries,
    snapshot.providers
FROM indexer_state state
LEFT JOIN LATERAL (
    SELECT source_kind, scanned_at, rpc_sources_total, rpc_sources_ok,
           visible_node_ids, unique_public_ips, geolocated_node_ids,
           geolocated_public_ips, node_id_ip_conflicts, region_count,
           country_count, provider_count, regions, countries, providers
    FROM network_distribution_snapshots
    WHERE chain_id = state.chain_id
    ORDER BY scanned_at DESC, id DESC
    LIMIT 1
) snapshot ON true
WHERE state.state_key = %s
"""

BLOCK_COLUMNS = """
    block.height,
    block.block_hash_hex,
    block.time_utc,
    block.proposer_address,
    profile.moniker AS proposer_moniker,
    block.tx_count
"""

BLOCK_DETAIL_COLUMNS = """
    block.height,
    block.block_hash_hex,
    block.block_hash_base64,
    block.time_utc,
    block.proposer_address,
    profile.moniker AS proposer_moniker,
    block.tx_count
"""

BLOCKS_SQL = f"""
SELECT {BLOCK_COLUMNS}
FROM blocks block
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
WHERE (%s::bigint IS NULL OR block.height < %s::bigint)
ORDER BY block.height DESC
LIMIT %s
"""

BLOCK_BY_HEX_SQL = f"""
SELECT {BLOCK_COLUMNS}
FROM blocks block
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
WHERE block.block_hash_hex = %s
"""

BLOCK_BY_BASE64_SQL = f"""
SELECT {BLOCK_COLUMNS}
FROM blocks block
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
WHERE block.block_hash_base64 = %s
"""

BLOCK_DETAIL_SQL = f"""
SELECT {BLOCK_DETAIL_COLUMNS}
FROM blocks block
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
WHERE block.height = %s
"""

BLOCK_COMMIT_SQL = """
SELECT
    count(vsm.signing_address)::bigint AS validators,
    count(vs.signing_address) FILTER (WHERE vs.signed = true)::bigint AS signed,
    count(vs.signing_address) FILTER (WHERE vs.vote_status = 'nil')::bigint AS nil,
    count(vs.signing_address) FILTER (WHERE vs.vote_status = 'absent')::bigint AS absent,
    count(vs.signing_address) FILTER (WHERE vs.vote_status = 'invalid')::bigint AS invalid,
    count(vsm.signing_address) FILTER (WHERE vs.signing_address IS NULL)::bigint AS unknown
FROM validator_set_members vsm
LEFT JOIN validator_signatures vs
  ON vs.height = vsm.height
 AND vs.signing_address = vsm.signing_address
WHERE vsm.height = %s
"""

BLOCK_TRANSACTIONS_SQL = """
SELECT
    tx_index,
    tx_hash_hex,
    raw_base64,
    raw_base64_length,
    decoded_byte_length,
    decode_status
FROM transactions
WHERE block_height = %s
ORDER BY tx_index ASC
"""

TRANSACTION_DETAIL_SQL = """
SELECT
    transaction.block_height,
    transaction.tx_index,
    transaction.tx_hash_hex,
    transaction.raw_base64,
    transaction.raw_base64_length,
    transaction.decoded_byte_length,
    transaction.decode_status,
    transaction.payload_summary,
    block.block_hash_hex,
    block.time_utc,
    block.proposer_address,
    profile.moniker AS proposer_moniker
FROM transactions transaction
JOIN blocks block
  ON block.height = transaction.block_height
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
WHERE transaction.block_height = %s
  AND transaction.tx_index = %s
"""

TRANSACTION_BY_HASH_SQL = """
SELECT
    block_height,
    tx_index,
    tx_hash_hex
FROM transactions
WHERE tx_hash_hex = %s
ORDER BY block_height DESC, tx_index DESC
LIMIT 1
"""

TRANSACTIONS_SQL = """
SELECT
    transaction.block_height,
    transaction.tx_index,
    transaction.tx_hash_hex,
    transaction.payload_summary,
    block.time_utc
FROM transactions transaction
JOIN blocks block
  ON block.height = transaction.block_height
WHERE (
    %s::bigint IS NULL
    OR transaction.block_height < %s::bigint
    OR (
        transaction.block_height = %s::bigint
        AND transaction.tx_index < %s::integer
    )
)
ORDER BY transaction.block_height DESC, transaction.tx_index DESC
LIMIT %s
"""

VALIDATORS_CHECKPOINT_SQL = """
SELECT
    s.last_finalized_height AS height,
    b.height IS NOT NULL AS block_exists,
    (SELECT count(*) FROM (
        SELECT height FROM blocks WHERE height <= s.last_finalized_height ORDER BY height DESC LIMIT 20
    ) recent_20) AS network_blocks_20,
    (SELECT count(*) FROM (
        SELECT height FROM blocks WHERE height <= s.last_finalized_height ORDER BY height DESC LIMIT 1000
    ) recent_1000) AS network_blocks_1000
FROM indexer_state s
LEFT JOIN blocks b ON b.height = s.last_finalized_height
WHERE s.state_key = %s
"""

ACTIVE_VALIDATORS_SQL = """
WITH recent_blocks AS MATERIALIZED (
    SELECT height, row_number() OVER (ORDER BY height DESC) AS position
    FROM (
        SELECT height FROM blocks WHERE height <= %s ORDER BY height DESC LIMIT 1000
    ) bounded_blocks
), current_validators AS MATERIALIZED (
    SELECT vsm.signing_address, vsm.voting_power, vsm.proposer_priority, validator.public_key_type
    FROM validator_set_members vsm
    LEFT JOIN validators validator ON validator.signing_address = vsm.signing_address
    WHERE vsm.height = %s
), membership_by_validator AS (
    SELECT membership.signing_address,
           count(*) FILTER (WHERE recent.position <= 20)::bigint AS active_blocks_20,
           count(*)::bigint AS active_blocks_1000
    FROM recent_blocks recent
    JOIN validator_set_members membership ON membership.height = recent.height
    JOIN current_validators current ON current.signing_address = membership.signing_address
    GROUP BY membership.signing_address
), signatures_by_validator AS (
    SELECT signature.signing_address,
           count(*) FILTER (WHERE recent.position <= 20)::bigint AS observed_signatures_20,
           count(*) FILTER (WHERE recent.position <= 20 AND signature.signed = true)::bigint AS signed_blocks_20,
           count(*) FILTER (WHERE recent.position <= 20 AND signature.vote_status = 'nil')::bigint AS nil_blocks_20,
           count(*) FILTER (WHERE recent.position <= 20 AND signature.vote_status = 'absent')::bigint AS absent_blocks_20,
           count(*) FILTER (WHERE recent.position <= 20 AND signature.vote_status = 'invalid')::bigint AS invalid_blocks_20,
           count(*)::bigint AS observed_signatures_1000,
           count(*) FILTER (WHERE signature.signed = true)::bigint AS signed_blocks_1000,
           count(*) FILTER (WHERE signature.vote_status = 'nil')::bigint AS nil_blocks_1000,
           count(*) FILTER (WHERE signature.vote_status = 'absent')::bigint AS absent_blocks_1000,
           count(*) FILTER (WHERE signature.vote_status = 'invalid')::bigint AS invalid_blocks_1000
    FROM recent_blocks recent
    JOIN validator_signatures signature ON signature.height = recent.height
    JOIN current_validators current ON current.signing_address = signature.signing_address
    GROUP BY signature.signing_address
)
SELECT current.signing_address AS address, current.public_key_type, current.voting_power,
       current.proposer_priority, profile.moniker, profile.operator_address, profile.server_type,
       profile.source_height AS valoper_source_height,
       COALESCE(membership.active_blocks_20, 0)::bigint AS active_blocks_20,
       COALESCE(signatures.signed_blocks_20, 0)::bigint AS signed_blocks_20,
       COALESCE(signatures.nil_blocks_20, 0)::bigint AS nil_blocks_20,
       COALESCE(signatures.absent_blocks_20, 0)::bigint AS absent_blocks_20,
       COALESCE(signatures.invalid_blocks_20, 0)::bigint AS invalid_blocks_20,
       GREATEST(COALESCE(membership.active_blocks_20, 0) - COALESCE(signatures.observed_signatures_20, 0), 0)::bigint AS unknown_blocks_20,
       COALESCE(membership.active_blocks_1000, 0)::bigint AS active_blocks_1000,
       COALESCE(signatures.signed_blocks_1000, 0)::bigint AS signed_blocks_1000,
       COALESCE(signatures.nil_blocks_1000, 0)::bigint AS nil_blocks_1000,
       COALESCE(signatures.absent_blocks_1000, 0)::bigint AS absent_blocks_1000,
       COALESCE(signatures.invalid_blocks_1000, 0)::bigint AS invalid_blocks_1000,
       GREATEST(COALESCE(membership.active_blocks_1000, 0) - COALESCE(signatures.observed_signatures_1000, 0), 0)::bigint AS unknown_blocks_1000
FROM current_validators current
LEFT JOIN membership_by_validator membership ON membership.signing_address = current.signing_address
LEFT JOIN signatures_by_validator signatures ON signatures.signing_address = current.signing_address
LEFT JOIN valoper_profiles profile ON profile.signing_address = current.signing_address
ORDER BY current.voting_power DESC, current.signing_address ASC
"""

VALIDATOR_IDENTITY_SQL = """
SELECT validator.signing_address AS address, validator.public_key_type, validator.public_key_value,
       validator.first_seen_height, validator.last_seen_height,
       profile.moniker, profile.operator_address, profile.signing_pubkey, profile.description, profile.server_type,
       profile.source_height AS valoper_source_height
FROM validators validator
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = validator.signing_address
WHERE validator.signing_address = %s
"""

VALIDATOR_SEARCH_SQL = """
WITH ranked AS (
    SELECT DISTINCT ON (validator.signing_address)
        validator.signing_address AS address,
        profile.moniker,
        profile.operator_address,
        CASE
            WHEN lower(validator.signing_address) = lower(%s) THEN 0
            WHEN lower(profile.operator_address) = lower(%s) THEN 1
            WHEN lower(profile.moniker) = lower(%s) THEN 2
            WHEN profile.moniker ILIKE %s ESCAPE E'\\\\' THEN 3
            ELSE 4
        END AS match_rank
    FROM validators validator
    LEFT JOIN valoper_profiles profile
      ON profile.signing_address = validator.signing_address
    WHERE validator.signing_address ILIKE %s ESCAPE E'\\\\'
       OR profile.operator_address ILIKE %s ESCAPE E'\\\\'
       OR profile.moniker ILIKE %s ESCAPE E'\\\\'
    ORDER BY validator.signing_address
)
SELECT address, moniker, operator_address
FROM ranked
ORDER BY match_rank,
         CASE WHEN moniker IS NULL THEN 1 ELSE 0 END,
         lower(moniker) NULLS LAST,
         address
LIMIT %s
"""

VALIDATOR_CURRENT_SQL = """
SELECT
    s.last_finalized_height AS height,
    b.height IS NOT NULL AS block_exists,
    current.voting_power,
    current.proposer_priority,
    COALESCE(total.voting_power, 0) AS total_voting_power
FROM indexer_state s
LEFT JOIN blocks b ON b.height = s.last_finalized_height
LEFT JOIN validator_set_members current
  ON current.height = s.last_finalized_height AND current.signing_address = %s
LEFT JOIN LATERAL (
    SELECT COALESCE(sum(voting_power), 0) AS voting_power
    FROM validator_set_members
    WHERE height = s.last_finalized_height
) total ON true
WHERE s.state_key = %s
"""

VALIDATOR_HISTORY_SQL = """
WITH recent_blocks AS (
    SELECT height, time_utc
    FROM blocks
    WHERE height <= %s
    ORDER BY height DESC
    LIMIT 1000
)
SELECT recent.height, recent.time_utc,
       membership.signing_address AS membership_address,
       signature.signing_address AS signature_address,
       signature.signed, signature.vote_status
FROM recent_blocks recent
LEFT JOIN validator_set_members membership
  ON membership.height = recent.height AND membership.signing_address = %s
LEFT JOIN validator_signatures signature
  ON signature.height = membership.height AND signature.signing_address = membership.signing_address
ORDER BY recent.height ASC
"""

VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL = """
SELECT height, time_utc
FROM (
    SELECT height, time_utc
    FROM blocks
    WHERE height <= %s
    ORDER BY height DESC
    LIMIT %s
) bounded_blocks
ORDER BY height ASC
"""

VALIDATOR_SIGNING_HISTORY_CHECKPOINT_SQL = """
SELECT
    s.last_finalized_height AS height,
    b.height IS NOT NULL AS block_exists,
    COALESCE(
        array_agg(
            current.signing_address
            ORDER BY current.voting_power DESC, current.signing_address ASC
        ) FILTER (WHERE current.signing_address IS NOT NULL),
        ARRAY[]::text[]
    ) AS validator_addresses
FROM indexer_state s
LEFT JOIN blocks b ON b.height = s.last_finalized_height
LEFT JOIN validator_set_members current ON current.height = s.last_finalized_height
WHERE s.state_key = %s
GROUP BY s.last_finalized_height, b.height
"""

VALIDATOR_SIGNING_HISTORY_MATRIX_SQL = """
WITH recent_blocks AS (
    SELECT height
    FROM (
        SELECT height
        FROM blocks
        WHERE height <= %s
        ORDER BY height DESC
        LIMIT %s
    ) bounded_blocks
), current_validators AS (
    SELECT signing_address, voting_power
    FROM validator_set_members
    WHERE height = %s
)
SELECT
    current.signing_address AS address,
    recent.height,
    membership.signing_address AS membership_address,
    signature.signing_address AS signature_address,
    signature.signed,
    signature.vote_status
FROM current_validators current
CROSS JOIN recent_blocks recent
LEFT JOIN validator_set_members membership
  ON membership.height = recent.height
 AND membership.signing_address = current.signing_address
LEFT JOIN validator_signatures signature
  ON signature.height = membership.height
 AND signature.signing_address = membership.signing_address
ORDER BY current.voting_power DESC, current.signing_address ASC, recent.height ASC
"""

GOVERNANCE_SOURCE_SQL = """
SELECT s.chain_id AS current_chain_id, sync.chain_id, sync.realm_path,
       sync.source_height, sync.page_count, sync.proposal_count,
       sync.first_proposal_id, sync.latest_proposal_id, sync.last_success_at,
       stats.actual_proposal_count, stats.actual_first_proposal_id,
       stats.actual_latest_proposal_id, stats.active_count, stats.accepted_count,
       stats.rejected_count, stats.unknown_count
FROM indexer_state s
LEFT JOIN governance_sync_state sync
  ON sync.chain_id = s.chain_id AND sync.realm_path = %s
LEFT JOIN LATERAL (
    SELECT count(*)::bigint AS actual_proposal_count,
           min(proposal_id) AS actual_first_proposal_id,
           max(proposal_id) AS actual_latest_proposal_id,
           count(*) FILTER (WHERE status = 'ACTIVE')::bigint AS active_count,
           count(*) FILTER (WHERE status = 'ACCEPTED')::bigint AS accepted_count,
           count(*) FILTER (WHERE status = 'REJECTED')::bigint AS rejected_count,
           count(*) FILTER (WHERE status = 'UNKNOWN')::bigint AS unknown_count
    FROM governance_proposals
    WHERE chain_id = s.chain_id AND realm_path = %s
) stats ON sync.chain_id IS NOT NULL
WHERE s.state_key = %s
"""

GOVERNANCE_PROPOSALS_SQL = """
SELECT proposal.proposal_id, proposal.title, proposal.author_display,
       proposal.author_address, proposal.status, proposal.eligible_tiers,
       proposal.yes_percent, proposal.no_percent, proposal.abstain_percent,
       (SELECT count(*)::bigint FROM (
            SELECT 1 FROM governance_votes vote
            WHERE vote.chain_id = proposal.chain_id
              AND vote.realm_path = proposal.realm_path
              AND vote.proposal_id = proposal.proposal_id
            LIMIT 1001
        ) bounded_votes) AS voter_count
FROM governance_proposals proposal
WHERE proposal.chain_id = %s AND proposal.realm_path = %s
  AND (%s::bigint IS NULL OR proposal.proposal_id < %s::bigint)
ORDER BY proposal.proposal_id DESC
LIMIT %s
"""

GOVERNANCE_PROPOSAL_DETAIL_SQL = """
SELECT proposal.proposal_id, proposal.title, proposal.author_display,
       proposal.author_address, proposal.status, proposal.eligible_tiers,
       proposal.description, proposal.executor_text,
       proposal.executor_creation_realm, proposal.rejection_reason,
       proposal.yes_percent, proposal.no_percent, proposal.abstain_percent,
       proposal.detail_parse_status, proposal.votes_parse_status,
       proposal.first_observed_height, proposal.last_observed_height,
       proposal.first_observed_at, proposal.last_observed_at,
       (SELECT count(*)::bigint FROM governance_votes vote
        WHERE vote.chain_id = proposal.chain_id AND vote.realm_path = proposal.realm_path
          AND vote.proposal_id = proposal.proposal_id) AS voter_count
FROM governance_proposals proposal
WHERE proposal.chain_id = %s AND proposal.realm_path = %s
  AND proposal.proposal_id = %s
"""

GOVERNANCE_VOTES_SQL = """
SELECT voter_display, voter_address, option, tier, voting_power::text AS voting_power,
       first_observed_height, last_observed_height, first_observed_at, last_observed_at
FROM governance_votes
WHERE chain_id = %s AND realm_path = %s AND proposal_id = %s
ORDER BY tier ASC, voter_key ASC
LIMIT 1001
"""

GOVERNANCE_TRANSACTION_SQL = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"


class MissingIndexerStateError(RuntimeError):
    """Raised when the singleton indexer state row is missing."""


class MissingIndexedBlockError(RuntimeError):
    """Raised when the completed checkpoint points to a missing block row."""


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
                cursor.execute(HEALTH_SQL, (True, True, True, "default"))
                row = cursor.fetchone()
        if row is None:
            raise MissingIndexerStateError("Default indexer state is missing")
        return dict(row)

    def _fetch_governance_source(self, cursor: Any, realm_path: str) -> dict[str, Any] | None:
        cursor.execute(GOVERNANCE_SOURCE_SQL, (realm_path, realm_path, "default"))
        row = cursor.fetchone()
        if row is None:
            raise MissingIndexerStateError("Default indexer state is missing")
        result = dict(row)
        return None if result["chain_id"] is None else result

    def fetch_governance_proposals(
        self, *, realm_path: str, limit: int, before_proposal_id: int | None
    ) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(GOVERNANCE_TRANSACTION_SQL)
                    source = self._fetch_governance_source(cursor, realm_path)
                    if source is None:
                        return None
                    cursor.execute(GOVERNANCE_PROPOSALS_SQL, (
                        source["chain_id"], realm_path, before_proposal_id,
                        before_proposal_id, limit + 1,
                    ))
                    rows = cursor.fetchall()
        return {"source": source, "items": [dict(row) for row in rows]}

    def fetch_governance_proposal_detail(
        self, *, realm_path: str, proposal_id: int
    ) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(GOVERNANCE_TRANSACTION_SQL)
                    source = self._fetch_governance_source(cursor, realm_path)
                    if source is None:
                        return None
                    identity = (source["chain_id"], realm_path, proposal_id)
                    cursor.execute(GOVERNANCE_PROPOSAL_DETAIL_SQL, identity)
                    proposal = cursor.fetchone()
                    if proposal is None:
                        return {"source": source, "proposal": None, "votes": []}
                    cursor.execute(GOVERNANCE_VOTES_SQL, identity)
                    votes = cursor.fetchall()
        return {
            "source": source,
            "proposal": dict(proposal),
            "votes": [dict(row) for row in votes],
        }

    def fetch_network_overview(self) -> dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(NETWORK_SQL, ("default",))
                row = cursor.fetchone()
        if row is None:
            if not self._default_indexer_state_exists():
                raise MissingIndexerStateError("Default indexer state is missing")
            raise MissingIndexedBlockError("Indexed block is missing")
        return dict(row)

    def fetch_network_distribution(self) -> dict[str, Any]:
        """Return the latest aggregate snapshot for the default indexer chain."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(NETWORK_DISTRIBUTION_SQL, ("default",))
                row = cursor.fetchone()
        if row is None:
            raise MissingIndexerStateError("Default indexer state is missing")
        return dict(row)

    def _default_indexer_state_exists(self) -> bool:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM indexer_state WHERE state_key = %s", ("default",))
                return cursor.fetchone() is not None

    def fetch_blocks(self, *, limit: int, before_height: int | None) -> list[dict[str, Any]]:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(BLOCKS_SQL, (before_height, before_height, limit + 1))
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def fetch_block_by_hash(self, *, normalized_hex: str | None, block_hash_base64: str | None) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        sql = BLOCK_BY_HEX_SQL if normalized_hex is not None else BLOCK_BY_BASE64_SQL
        value = normalized_hex if normalized_hex is not None else block_hash_base64
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (value,))
                row = cursor.fetchone()
        return None if row is None else dict(row)

    def fetch_block_detail(self, height: int) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(BLOCK_DETAIL_SQL, (height,))
                block_row = cursor.fetchone()
                if block_row is None:
                    return None

                cursor.execute(BLOCK_COMMIT_SQL, (height,))
                commit_row = cursor.fetchone()

                cursor.execute(BLOCK_TRANSACTIONS_SQL, (height,))
                transaction_rows = cursor.fetchall()

        commit = dict(commit_row) if commit_row is not None else {}
        for key in ("validators", "signed", "nil", "absent", "invalid", "unknown"):
            commit[key] = int(commit.get(key) or 0)
        commit["missed"] = commit["nil"] + commit["absent"] + commit["invalid"]

        return {
            "block": dict(block_row),
            "commit": commit,
            "transactions": [dict(row) for row in transaction_rows],
        }

    def fetch_transaction_detail(self, block_height: int, tx_index: int) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(TRANSACTION_DETAIL_SQL, (block_height, tx_index))
                row = cursor.fetchone()
        return None if row is None else dict(row)

    def fetch_transaction_by_hash(self, tx_hash: str) -> dict[str, Any] | None:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(TRANSACTION_BY_HASH_SQL, (tx_hash,))
                row = cursor.fetchone()
        return None if row is None else dict(row)

    def fetch_transactions(
        self,
        *,
        limit: int,
        before_height: int | None,
        before_tx_index: int | None,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    TRANSACTIONS_SQL,
                    (before_height, before_height, before_height, before_tx_index, limit + 1),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def fetch_active_validators(self) -> dict[str, Any]:
        """Return the checkpoint and its active validators using one pooled connection."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(VALIDATORS_CHECKPOINT_SQL, ("default",))
                checkpoint = cursor.fetchone()
                if checkpoint is None:
                    raise MissingIndexerStateError("Default indexer state is missing")
                checkpoint = dict(checkpoint)
                if not checkpoint["block_exists"]:
                    raise MissingIndexedBlockError("Indexed block is missing")
                height = checkpoint["height"]
                cursor.execute(ACTIVE_VALIDATORS_SQL, (height, height))
                rows = cursor.fetchall()
        return {"checkpoint": checkpoint, "items": [dict(row) for row in rows]}

    def fetch_validator_detail(self, address: str) -> dict[str, Any] | None:
        """Return identity, checkpoint membership, and bounded history on one connection."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(VALIDATOR_IDENTITY_SQL, (address,))
                identity = cursor.fetchone()
                if identity is None:
                    return None

                cursor.execute(VALIDATOR_CURRENT_SQL, (address, "default"))
                current = cursor.fetchone()
                if current is None:
                    raise MissingIndexerStateError("Default indexer state is missing")
                current = dict(current)
                if not current["block_exists"]:
                    raise MissingIndexedBlockError("Indexed block is missing")

                cursor.execute(VALIDATOR_HISTORY_SQL, (current["height"], address))
                history = cursor.fetchall()

        return {
            "identity": dict(identity),
            "current": current,
            "history": [dict(row) for row in history],
        }

    def fetch_validator_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return compact validator identities matching literal search text."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        normalized = query.strip()
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix = f"{escaped}%"
        contains = f"%{escaped}%"
        parameters = (normalized, normalized, normalized, prefix, contains, contains, contains, limit)
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(VALIDATOR_SEARCH_SQL, parameters)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def fetch_validator_signing_history(self, *, limit: int) -> dict[str, Any]:
        """Return a bounded history matrix for the current active set."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(VALIDATOR_SIGNING_HISTORY_CHECKPOINT_SQL, ("default",))
                checkpoint = cursor.fetchone()
                if checkpoint is None:
                    raise MissingIndexerStateError("Default indexer state is missing")
                checkpoint = dict(checkpoint)
                if not checkpoint["block_exists"]:
                    raise MissingIndexedBlockError("Indexed block is missing")
                height = checkpoint["height"]

                cursor.execute(VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL, (height, limit))
                blocks = cursor.fetchall()
                cursor.execute(VALIDATOR_SIGNING_HISTORY_MATRIX_SQL, (height, limit, height))
                items = cursor.fetchall()

        return {
            "checkpoint": checkpoint,
            "blocks": [dict(row) for row in blocks],
            "items": [dict(row) for row in items],
        }


database = ApiDatabase()


def isoformat_utc_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
