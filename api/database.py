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
    r.last_checked_at AS rpc_last_checked_at,
    r.latency_ms AS rpc_latency_ms,
    rpc_pool.endpoints AS rpc_pool_endpoints,
    COALESCE(rpc_pool.total, 0) AS rpc_pool_total,
    COALESCE(rpc_pool.available, 0) AS rpc_pool_available,
    rpc_pool.last_checked_at AS rpc_pool_last_checked_at
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
LEFT JOIN LATERAL (
    SELECT
        count(*)::integer AS total,
        count(*) FILTER (WHERE endpoint.state = 'healthy')::integer AS available,
        max(endpoint.last_checked_at) AS last_checked_at,
        jsonb_agg(jsonb_build_object(
            'url', endpoint.url, 'selected', endpoint.is_selected,
            'state', endpoint.state, 'latency_ms', endpoint.latency_ms,
            'lag', endpoint.observed_lag, 'last_checked_at', endpoint.last_checked_at
        ) ORDER BY
            endpoint.is_selected DESC,
            (endpoint.state = 'healthy') DESC,
            endpoint.latency_ms ASC NULLS LAST,
            endpoint.url ASC
        ) AS endpoints
    FROM (
        SELECT bounded.*,
            CASE
                WHEN bounded.catching_up = true THEN 'catching_up'
                WHEN bounded.healthy = true THEN 'healthy'
                WHEN bounded.last_checked_at IS NULL OR bounded.healthy IS NULL THEN 'unknown'
                WHEN bounded.last_error ~* '(wrong[ _-]?chain|chain[ _-]?id)' THEN 'wrong_chain'
                WHEN bounded.last_error ~* 'stale' OR (bounded.healthy = false AND bounded.observed_lag > 1) THEN 'stale'
                ELSE 'unavailable'
            END AS state
        FROM rpc_endpoints bounded
        WHERE bounded.chain_id = s.chain_id AND bounded.is_enabled = true
        ORDER BY bounded.is_selected DESC, bounded.url
        LIMIT 32
    ) endpoint
) rpc_pool ON true
WHERE s.state_key = %s
"""

ACCOUNT_VALIDATOR_RELATION_SQL = """
SELECT moniker, operator_address, signing_address
FROM valoper_profiles
WHERE operator_address = %s
LIMIT 2
"""

SELECTED_RPC_URL_SQL = """
SELECT endpoint.url
FROM indexer_state state
JOIN rpc_endpoints endpoint
  ON endpoint.id = state.selected_rpc_endpoint_id
 AND endpoint.chain_id = state.chain_id
WHERE state.state_key = %s
  AND state.chain_id = %s
  AND endpoint.is_selected = true
  AND endpoint.is_enabled = true
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

REALM_CATALOG_SUMMARY_SQL = """
SELECT s.chain_id, i.last_finalized_height AS indexed_height, s.observed_height,
 s.refreshed_at, s.activity_from_height, s.activity_through_height,
 count(c.*)::bigint AS total_items,
 count(*) FILTER (WHERE c.path_kind='realm')::bigint AS total_realms,
 count(*) FILTER (WHERE c.path_kind='package')::bigint AS total_packages,
 count(*) FILTER (WHERE c.rpc_visible)::bigint AS rpc_visible_items,
 count(*) FILTER (WHERE c.last_activity_at >= now() - interval '24 hours')::bigint AS active_24h
FROM realm_catalog_state s JOIN indexer_state i ON i.state_key='default' AND i.chain_id=s.chain_id
LEFT JOIN realm_catalog c ON c.chain_id=s.chain_id
WHERE s.chain_id=%s
GROUP BY s.chain_id,i.last_finalized_height,s.observed_height,s.refreshed_at,s.activity_from_height,s.activity_through_height
"""
REALM_CATALOG_ITEMS_SQL = """
SELECT path,path_kind,rpc_visible,deployer_address,deploy_height,deploy_tx_index,first_seen_height,
 last_activity_height,last_activity_tx_index,last_activity_at,call_count,successful_call_count,
 failed_call_count,unknown_result_call_count
FROM realm_catalog WHERE chain_id=%s AND (%s='all' OR path_kind=%s)
 AND (%s::text IS NULL OR strpos(lower(path), lower(%s::text)) > 0)
 AND (%s::bigint IS NULL OR COALESCE(last_activity_height,-1) < %s::bigint OR
      (COALESCE(last_activity_height,-1) = %s::bigint AND path > %s::text))
ORDER BY COALESCE(last_activity_height,-1) DESC,path ASC LIMIT %s
"""
REALM_DETAIL_SOURCE_SQL = """
SELECT s.chain_id, i.last_finalized_height AS indexed_height, s.observed_height, s.refreshed_at,
 s.activity_from_height, s.activity_through_height, call_state.chain_id AS call_chain_id,
 call_state.from_height AS call_index_from_height, call_state.through_height AS call_index_through_height
FROM realm_catalog_state s
JOIN indexer_state i ON i.state_key='default' AND i.chain_id=s.chain_id
LEFT JOIN realm_call_index_state call_state ON call_state.chain_id=s.chain_id
WHERE s.chain_id=%s
"""
REALM_DETAIL_ITEM_SQL = """
SELECT chain_id,path,path_kind,rpc_visible,deployer_address,deploy_height,deploy_tx_index,first_seen_height,
 last_activity_height,last_activity_tx_index,last_activity_at,call_count,successful_call_count,
 failed_call_count,unknown_result_call_count
FROM realm_catalog WHERE chain_id=%s AND path=%s
"""
REALM_CALLS_PAGE_SQL = """
SELECT
    call.block_height,
    call.tx_index,
    call.message_index,
    call.caller_address,
    call.function_name,
    call.args_count,
    call.send_amount,
    tx.tx_hash_hex,
    block.time_utc,
    result.execution_status,
    result.gas_wanted::text AS gas_wanted,
    result.gas_used::text AS gas_used
FROM realm_call_index call
JOIN transactions tx
  ON (tx.block_height, tx.tx_index)
   = (call.block_height, call.tx_index)
JOIN blocks block
  ON block.height = call.block_height
LEFT JOIN transaction_execution_results result
  ON (result.block_height, result.tx_index)
   = (call.block_height, call.tx_index)
WHERE call.chain_id = %s
  AND call.path = %s
  AND (
      %s::bigint IS NULL
      OR (
          call.block_height,
          call.tx_index,
          call.message_index
      ) < (
          %s::bigint,
          %s::integer,
          %s::integer
      )
  )
ORDER BY
    call.block_height DESC,
    call.tx_index DESC,
    call.message_index DESC
LIMIT %s
"""

REALM_TOP_ITEMS_SQL = """
SELECT path,path_kind,rpc_visible,deployer_address,deploy_height,deploy_tx_index,first_seen_height,
 last_activity_height,last_activity_tx_index,last_activity_at,call_count,successful_call_count,
 failed_call_count,unknown_result_call_count
FROM realm_catalog
WHERE chain_id = %s
  AND path_kind = 'realm'
  AND rpc_visible = true
  AND call_count > 0
ORDER BY
    call_count DESC,
    COALESCE(last_activity_height, -1) DESC,
    path COLLATE "C" ASC
LIMIT %s
"""
REALM_NAMESPACE_TOP_SQL = """
WITH realm_rows AS MATERIALIZED (
 SELECT split_part(path, '/', 3) COLLATE "C" AS namespace_key, path, path_kind, rpc_visible, first_seen_height,
  last_activity_height,last_activity_tx_index,last_activity_at,call_count,successful_call_count,
  failed_call_count,unknown_result_call_count
 FROM realm_catalog WHERE chain_id=%s AND path_kind='realm'
), namespace_aggregates AS (
 SELECT namespace_key,count(*)::bigint realm_count,count(*) FILTER (WHERE call_count>0)::bigint called_realm_count,
  count(*) FILTER (WHERE rpc_visible)::bigint rpc_visible_realm_count,sum(call_count)::bigint direct_call_count,
  sum(successful_call_count)::bigint successful_call_count,sum(failed_call_count)::bigint failed_call_count,
  sum(unknown_result_call_count)::bigint unknown_result_call_count,min(first_seen_height) first_seen_height
 FROM realm_rows WHERE (NOT %s OR namespace_key=ANY(%s::text[])) GROUP BY namespace_key
), ranked_activity AS (
 SELECT namespace_key,path AS latest_activity_path,path_kind,call_count,last_activity_height,last_activity_tx_index,last_activity_at,
  row_number() OVER (PARTITION BY namespace_key ORDER BY last_activity_height DESC NULLS LAST,
   last_activity_tx_index DESC NULLS LAST,path COLLATE "C" ASC) activity_number
 FROM realm_rows WHERE call_count>0
), latest_activity AS (
 SELECT namespace_key,latest_activity_path,path_kind AS latest_activity_path_kind,
  call_count AS latest_activity_call_count,last_activity_height,last_activity_tx_index,last_activity_at
 FROM ranked_activity WHERE activity_number=1
)
SELECT a.*,l.latest_activity_path,l.latest_activity_path_kind,l.latest_activity_call_count,
 l.last_activity_height,l.last_activity_tx_index,l.last_activity_at
FROM namespace_aggregates a JOIN latest_activity l ON a.namespace_key=l.namespace_key COLLATE "C"
WHERE rpc_visible_realm_count>0 AND direct_call_count>0
ORDER BY
 a.direct_call_count DESC,
 COALESCE(l.last_activity_height,-1) DESC,
 a.namespace_key COLLATE "C" ASC
LIMIT %s
"""
REALM_NAMESPACE_MEMBERS_SQL = """
WITH ranked AS (
 SELECT split_part(path,'/',3) COLLATE "C" namespace_key,path,path_kind,rpc_visible,first_seen_height,last_activity_height,
  last_activity_tx_index,last_activity_at,call_count,successful_call_count,failed_call_count,unknown_result_call_count,
  row_number() OVER (PARTITION BY split_part(path,'/',3) COLLATE "C" ORDER BY path COLLATE "C") member_number
 FROM realm_catalog WHERE chain_id=%s AND path_kind='realm' AND split_part(path,'/',3) COLLATE "C"=ANY(%s::text[])
)
SELECT * FROM ranked WHERE member_number<=100 ORDER BY namespace_key COLLATE "C",path COLLATE "C"
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
    transaction.tx_index,
    transaction.tx_hash_hex,
    transaction.raw_base64,
    transaction.raw_base64_length,
    transaction.decoded_byte_length,
    transaction.decode_status,
    result.execution_status, result.gas_wanted::text AS gas_wanted,
    result.gas_used::text AS gas_used, result.error_text AS error,
    result.log_text AS log, result.info_text AS info
FROM transactions transaction
LEFT JOIN transaction_execution_results result
  ON (result.block_height, result.tx_index) = (transaction.block_height, transaction.tx_index)
WHERE transaction.block_height = %s
ORDER BY transaction.tx_index ASC
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
    profile.moniker AS proposer_moniker,
    result.execution_status, result.gas_wanted::text AS gas_wanted,
    result.gas_used::text AS gas_used, result.error_text AS error,
    result.log_text AS log, result.info_text AS info
FROM transactions transaction
JOIN blocks block
  ON block.height = transaction.block_height
LEFT JOIN valoper_profiles profile
  ON profile.signing_address = block.proposer_address
LEFT JOIN transaction_execution_results result
  ON (result.block_height, result.tx_index) = (transaction.block_height, transaction.tx_index)
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
    block.time_utc,
    result.execution_status, result.gas_wanted::text AS gas_wanted,
    result.gas_used::text AS gas_used, result.error_text AS error,
    result.log_text AS log, result.info_text AS info
FROM transactions transaction
JOIN blocks block
  ON block.height = transaction.block_height
LEFT JOIN transaction_execution_results result
  ON (result.block_height, result.tx_index) = (transaction.block_height, transaction.tx_index)
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

ACCOUNT_TRANSACTIONS_SQL = """
SELECT
    participant.block_height,
    participant.tx_index,
    transaction.tx_hash_hex,
    transaction.payload_summary,
    block.time_utc,
    result.execution_status, result.gas_wanted::text AS gas_wanted,
    result.gas_used::text AS gas_used, result.error_text AS error,
    result.log_text AS log, result.info_text AS info,
    jsonb_agg(jsonb_build_object(
        'message_index', participant.message_index,
        'role', participant.role
    ) ORDER BY participant.message_index, participant.role) AS participation
FROM transaction_participants participant
JOIN transactions transaction
  ON (transaction.block_height, transaction.tx_index) =
     (participant.block_height, participant.tx_index)
JOIN blocks block ON block.height = participant.block_height
LEFT JOIN transaction_execution_results result
  ON (result.block_height, result.tx_index) = (transaction.block_height, transaction.tx_index)
WHERE participant.address = %s
  AND (
      %s::bigint IS NULL
      OR participant.block_height < %s::bigint
      OR (participant.block_height = %s::bigint AND participant.tx_index < %s::integer)
  )
GROUP BY participant.block_height, participant.tx_index, transaction.tx_hash_hex,
         transaction.payload_summary, block.time_utc, result.execution_status,
         result.gas_wanted, result.gas_used, result.error_text, result.log_text,
         result.info_text
ORDER BY participant.block_height DESC, participant.tx_index DESC
LIMIT %s
"""

VALIDATORS_CHECKPOINT_SQL = """
SELECT
    s.last_finalized_height AS height,
    b.height IS NOT NULL AS block_exists,
    (SELECT count(*) FROM (
        SELECT height FROM blocks WHERE height <= s.last_finalized_height ORDER BY height DESC LIMIT 1000
    ) recent_1000) AS network_blocks_1000
FROM indexer_state s
LEFT JOIN blocks b ON b.height = s.last_finalized_height
WHERE s.state_key = %s
"""

ACTIVE_VALIDATORS_SQL = """
WITH recent_blocks AS MATERIALIZED (
    SELECT height
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
           count(*)::bigint AS active_blocks_1000
    FROM recent_blocks recent
    JOIN validator_set_members membership ON membership.height = recent.height
    JOIN current_validators current ON current.signing_address = membership.signing_address
    GROUP BY membership.signing_address
), signatures_by_validator AS (
    SELECT signature.signing_address,
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

    def fetch_realm_catalog(self, *, chain_id: str, limit: int, kind: str, q: str | None,
                            before_activity_height: int | None, before_path: str | None) -> dict[str, Any] | None:
        """Read one consistent PostgreSQL-only catalog page."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(REALM_CATALOG_SUMMARY_SQL, (chain_id,))
            summary = cursor.fetchone()
            if summary is None:
                return None
            cursor.execute(REALM_CATALOG_ITEMS_SQL, (chain_id, kind, kind, q, q,
                before_activity_height, before_activity_height, before_activity_height, before_path, limit + 1))
            rows = cursor.fetchall()
        return {"summary": dict(summary), "items": [dict(row) for row in rows]}


    def fetch_realm_detail(self, *, chain_id: str, path: str) -> dict[str, Any] | None:
        """Read an exact Realm or Package catalog detail from one read-only snapshot."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(REALM_DETAIL_ITEM_SQL, (chain_id, path))
            item = cursor.fetchone()
            if item is None:
                return {"source": None, "item": None}
            cursor.execute(REALM_DETAIL_SOURCE_SQL, (chain_id,))
            source = cursor.fetchone()
        return {"source": dict(source) if source is not None else None, "item": dict(item)}

    def fetch_realm_calls(self, *, chain_id: str, path: str, limit: int,
                          before_height: int | None, before_tx_index: int | None,
                          before_message_index: int | None) -> dict[str, Any] | None:
        """Read a Realm call page after coverage validation in one read-only snapshot."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(REALM_DETAIL_ITEM_SQL, (chain_id, path))
            item = cursor.fetchone()
            if item is None:
                return None
            cursor.execute(REALM_DETAIL_SOURCE_SQL, (chain_id,))
            source = cursor.fetchone()
            if source is None:
                return {"source": None, "item": dict(item), "items": []}
            cursor.execute(REALM_CALLS_PAGE_SQL, (chain_id, path, before_height, before_height, before_tx_index,
                before_message_index, limit + 1))
            rows = cursor.fetchall()
        return {"source": dict(source), "item": dict(item), "items": [dict(row) for row in rows]}

    def fetch_top_realms(self, *, chain_id: str, limit: int) -> dict[str, Any] | None:
        """Read ranking rows and their catalog source from one read-only snapshot."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(REALM_CATALOG_SUMMARY_SQL, (chain_id,))
            source = cursor.fetchone()
            if source is None:
                return None
            cursor.execute(REALM_TOP_ITEMS_SQL, (chain_id, limit))
            rows = cursor.fetchall()
        return {"source": dict(source), "items": [dict(row) for row in rows]}

    def fetch_top_realm_namespaces(self, *, chain_id: str, limit: int, curated_only: bool,
                                   curated_namespace_keys: tuple[str, ...]) -> dict[str, Any] | None:
        """Read namespace aggregates, members, and source from one stable snapshot."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(REALM_CATALOG_SUMMARY_SQL, (chain_id,))
            source = cursor.fetchone()
            if source is None:
                return None
            cursor.execute(REALM_NAMESPACE_TOP_SQL, (chain_id, curated_only, list(curated_namespace_keys), limit))
            rows = [dict(row) for row in cursor.fetchall()]
            keys = tuple(row["namespace_key"] for row in rows)
            members = []
            if keys:
                cursor.execute(REALM_NAMESPACE_MEMBERS_SQL, (chain_id, list(keys)))
                members = [dict(row) for row in cursor.fetchall()]
        return {"source": dict(source), "items": rows, "members": members}

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

    def fetch_account_transactions(
        self, address: str, *, limit: int, before_height: int | None,
        before_tx_index: int | None,
    ) -> list[dict[str, Any]]:
        """Read one deduplicated Account-history page from the participant index."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    ACCOUNT_TRANSACTIONS_SQL,
                    (address, before_height, before_height, before_height,
                     before_tx_index, limit + 1),
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

    def fetch_account_validator_relation(self, address: str) -> dict[str, Any] | None:
        """Return one exact operator profile while detecting inconsistent duplicates."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(ACCOUNT_VALIDATOR_RELATION_SQL, (address,))
                rows = cursor.fetchall()
        if len(rows) > 1:
            raise RuntimeError("Duplicate validator operator profiles")
        return None if not rows else dict(rows[0])

    def fetch_selected_rpc_url(self, chain_id: str) -> str | None:
        """Return the consistent canonical RPC URL without modifying selection state."""
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection(timeout=2.0) as connection:
            with connection.cursor() as cursor:
                cursor.execute(SELECTED_RPC_URL_SQL, ("default", chain_id))
                row = cursor.fetchone()
        return None if row is None else row["url"]

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
