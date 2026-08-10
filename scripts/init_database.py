#!/usr/bin/env python3
"""Initialize or validate the PostgreSQL schema without exposing DATABASE_URL in argv."""
from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "database" / "schema.sql"
PARTICIPANT_MIGRATION = REPO_ROOT / "database" / "migrations" / "0006_add_transaction_participants.sql"
EXECUTION_RESULT_MIGRATION = REPO_ROOT / "database" / "migrations" / "0007_add_transaction_execution_results.sql"
REALM_CATALOG_MIGRATION = REPO_ROOT / "database" / "migrations" / "0008_add_realm_catalog.sql"
REALM_CALL_INDEX_MIGRATION = REPO_ROOT / "database" / "migrations" / "0009_add_realm_call_index.sql"
REALM_METADATA_MIGRATION = REPO_ROOT / "database" / "migrations" / "0010_add_realm_metadata.sql"
EXPECTED_TABLES = {
    "blocks", "transactions", "validators", "validator_set_members", "validator_signatures", "rpc_endpoints", "rpc_endpoint_checks", "indexer_state", "valoper_profiles", "valopers_snapshot_state",
}
EXPECTED_COLUMNS = {
    "blocks": {
        "height": ("bigint", "NO", "", None), "block_hash_base64": ("text", "NO", "", None), "block_hash_hex": ("text", "NO", "", None),
        "time_utc": ("timestamp with time zone", "NO", "", None), "proposer_address": ("text", "YES", "", None), "tx_count": ("integer", "NO", "", None),
        "raw_block_response": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "transactions": {
        "id": ("bigint", "NO", "a", None), "block_height": ("bigint", "NO", "", None), "tx_index": ("integer", "NO", "", None), "raw_base64": ("text", "NO", "", None),
        "raw_base64_length": ("integer", "NO", "", None), "decoded_bytes": ("bytea", "YES", "", None), "decoded_byte_length": ("integer", "YES", "", None),
        "decode_status": ("text", "NO", "", None), "tx_hash_hex": ("text", "YES", "", None), "payload_summary": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validators": {
        "signing_address": ("text", "NO", "", None), "public_key_type": ("text", "NO", "", None), "public_key_value": ("text", "NO", "", None),
        "first_seen_height": ("bigint", "NO", "", None), "last_seen_height": ("bigint", "NO", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validator_set_members": {
        "height": ("bigint", "NO", "", None), "signing_address": ("text", "NO", "", None), "voting_power": ("numeric(78,0)", "NO", "", None),
        "proposer_priority": ("numeric(78,0)", "YES", "", None), "validator_index": ("integer", "YES", "", None), "raw_validator": ("jsonb", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "validator_signatures": {
        "height": ("bigint", "NO", "", None), "signing_address": ("text", "NO", "", None), "vote_status": ("text", "NO", "", None), "signed": ("boolean", "NO", "", None),
        "vote_block_id_hash_base64": ("text", "YES", "", None), "vote_block_id_hash_hex": ("text", "YES", "", None), "vote_block_id_parts_total": ("integer", "YES", "", None),
        "vote_block_id_parts_hash_base64": ("text", "YES", "", None), "vote_block_id_parts_hash_hex": ("text", "YES", "", None), "vote_block_id_is_zero": ("boolean", "NO", "", "false"),
        "block_id_matches_commit": ("boolean", "NO", "", "false"), "signature_base64": ("text", "YES", "", None), "raw_precommit": ("jsonb", "YES", "", None),
        "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "rpc_endpoints": {
        "id": ("bigint", "NO", "a", None), "url": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "is_enabled": ("boolean", "NO", "", "true"), "is_selected": ("boolean", "NO", "", "false"),
        "last_checked_at": ("timestamp with time zone", "YES", "", None), "last_selected_at": ("timestamp with time zone", "YES", "", None), "latest_observed_height": ("bigint", "YES", "", None), "observed_lag": ("bigint", "YES", "", None),
        "catching_up": ("boolean", "YES", "", None), "healthy": ("boolean", "YES", "", None), "last_error": ("text", "YES", "", None), "latency_ms": ("integer", "YES", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "rpc_endpoint_checks": {
        "id": ("bigint", "NO", "a", None), "rpc_endpoint_id": ("bigint", "NO", "", None), "checked_at": ("timestamp with time zone", "NO", "", "now()"), "chain_id": ("text", "NO", "", None),
        "latest_observed_height": ("bigint", "YES", "", None), "observed_lag": ("bigint", "YES", "", None), "catching_up": ("boolean", "YES", "", None), "healthy": ("boolean", "NO", "", None),
        "selected_for_cycle": ("boolean", "NO", "", "false"), "switch_reason": ("text", "YES", "", None), "error_message": ("text", "YES", "", None),
    },
    "indexer_state": {
        "state_key": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "last_finalized_height": ("bigint", "NO", "", None), "finalized_tip_height": ("bigint", "YES", "", None), "selected_rpc_endpoint_id": ("bigint", "YES", "", None), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "valoper_profiles": {
        "operator_address": ("text", "NO", "", None), "moniker": ("text", "NO", "", None), "description": ("text", "NO", "", None), "server_type": ("text", "NO", "", None), "signing_address": ("text", "NO", "", None), "signing_pubkey": ("text", "NO", "", None), "source_height": ("bigint", "NO", "", None), "list_position": ("integer", "NO", "", None), "inserted_at": ("timestamp with time zone", "NO", "", "now()"), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
    "valopers_snapshot_state": {
        "state_key": ("text", "NO", "", None), "chain_id": ("text", "NO", "", None), "source_height": ("bigint", "NO", "", None), "page_count": ("integer", "NO", "", None), "profile_count": ("integer", "NO", "", None), "updated_at": ("timestamp with time zone", "NO", "", "now()"),
    },
}
EXPECTED_PRIMARY_KEYS = {"blocks": ("height",), "transactions": ("id",), "validators": ("signing_address",), "validator_set_members": ("height", "signing_address"), "validator_signatures": ("height", "signing_address"), "rpc_endpoints": ("id",), "rpc_endpoint_checks": ("id",), "indexer_state": ("state_key",), "valoper_profiles": ("operator_address",), "valopers_snapshot_state": ("state_key",)}
EXPECTED_UNIQUES = {("blocks", ("block_hash_base64",)), ("blocks", ("block_hash_hex",)), ("transactions", ("block_height", "tx_index")), ("validators", ("public_key_type", "public_key_value")), ("rpc_endpoints", ("url",)), ("valoper_profiles", ("signing_address",)), ("valoper_profiles", ("signing_pubkey",))}
EXPECTED_FOREIGN_KEYS = {
    ("transactions", ("block_height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("height",), "blocks", ("height",), "c"),
    ("validator_set_members", ("signing_address",), "validators", ("signing_address",), "r"),
    ("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "c"),
    ("rpc_endpoint_checks", ("rpc_endpoint_id",), "rpc_endpoints", ("id",), "c"),
    ("indexer_state", ("selected_rpc_endpoint_id",), "rpc_endpoints", ("id",), "n"),
}
EXPECTED_CHECKS = {
    "blocks_tx_count_check": "CHECK (tx_count >= 0)",
    "blocks_block_hash_hex_uppercase": "CHECK (block_hash_hex = upper(block_hash_hex))",
    "transactions_tx_index_check": "CHECK (tx_index >= 0)",
    "transactions_raw_base64_length_check": "CHECK (raw_base64_length >= 0)",
    "transactions_decoded_byte_length_check": "CHECK (decoded_byte_length IS NULL OR decoded_byte_length >= 0)",
    "transactions_decode_status_check": "CHECK (decode_status IN ('decoded', 'invalid_base64', 'not_attempted'))",
    "transactions_raw_base64_length_matches": "CHECK (raw_base64_length = char_length(raw_base64))",
    "transactions_decode_status_consistent": "CHECK ((decode_status = 'decoded' AND decoded_bytes IS NOT NULL AND decoded_byte_length = octet_length(decoded_bytes)) OR (decode_status IN ('invalid_base64', 'not_attempted') AND decoded_bytes IS NULL AND decoded_byte_length IS NULL))",
    "transactions_tx_hash_hex_format": "CHECK (tx_hash_hex IS NULL OR tx_hash_hex ~ '^[0-9A-F]{64}$')",
    "transactions_tx_hash_consistent": "CHECK ((decode_status = 'decoded' AND tx_hash_hex IS NOT NULL) OR (decode_status IN ('invalid_base64', 'not_attempted') AND tx_hash_hex IS NULL))",
    "validators_first_seen_height_check": "CHECK (first_seen_height >= 0)",
    "validators_last_seen_height_check": "CHECK (last_seen_height >= first_seen_height)",
    "validator_set_members_voting_power_check": "CHECK (voting_power >= 0)",
    "validator_set_members_validator_index_check": "CHECK (validator_index IS NULL OR validator_index >= 0)",
    "validator_signatures_vote_status_check": "CHECK (vote_status IN ('commit', 'nil', 'absent', 'invalid'))",
    "validator_signatures_vote_block_id_parts_total_check": "CHECK (vote_block_id_parts_total IS NULL OR vote_block_id_parts_total >= 0)",
    "validator_signatures_signed_only_matching_commit": "CHECK (signed = (vote_status = 'commit' AND block_id_matches_commit))",
    "validator_signatures_commit_vote_consistent": "CHECK (vote_status <> 'commit' OR (block_id_matches_commit AND NOT vote_block_id_is_zero AND vote_block_id_hash_base64 IS NOT NULL AND vote_block_id_hash_hex IS NOT NULL AND vote_block_id_parts_total IS NOT NULL AND vote_block_id_parts_hash_base64 IS NOT NULL AND vote_block_id_parts_hash_hex IS NOT NULL AND signature_base64 IS NOT NULL))",
    "validator_signatures_nil_vote_consistent": "CHECK (vote_status <> 'nil' OR (NOT signed AND vote_block_id_is_zero AND NOT block_id_matches_commit))",
    "validator_signatures_absent_vote_consistent": "CHECK (vote_status <> 'absent' OR (NOT signed AND NOT vote_block_id_is_zero AND NOT block_id_matches_commit AND vote_block_id_hash_base64 IS NULL AND vote_block_id_hash_hex IS NULL AND vote_block_id_parts_total IS NULL AND vote_block_id_parts_hash_base64 IS NULL AND vote_block_id_parts_hash_hex IS NULL AND signature_base64 IS NULL AND raw_precommit IS NULL))",
    "validator_signatures_invalid_vote_consistent": "CHECK (vote_status <> 'invalid' OR (NOT signed AND NOT block_id_matches_commit))",
    "validator_signatures_vote_hash_hex_uppercase": "CHECK (vote_block_id_hash_hex IS NULL OR vote_block_id_hash_hex = upper(vote_block_id_hash_hex))",
    "validator_signatures_vote_parts_hash_hex_uppercase": "CHECK (vote_block_id_parts_hash_hex IS NULL OR vote_block_id_parts_hash_hex = upper(vote_block_id_parts_hash_hex))",
    "rpc_endpoints_latest_observed_height_check": "CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0)",
    "rpc_endpoints_observed_lag_check": "CHECK (observed_lag IS NULL OR observed_lag >= 0)",
    "rpc_endpoints_no_secret_url": "CHECK (url !~* '(password|token|apikey|api_key|secret)=')",
    "rpc_endpoints_latency_ms_check": "CHECK (latency_ms IS NULL OR latency_ms BETWEEN 0 AND 30000)",
    "rpc_endpoint_checks_latest_observed_height_check": "CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0)",
    "rpc_endpoint_checks_observed_lag_check": "CHECK (observed_lag IS NULL OR observed_lag >= 0)",
    "indexer_state_last_finalized_height_check": "CHECK (last_finalized_height >= 0)",
    "indexer_state_finalized_tip_height_check": "CHECK (finalized_tip_height IS NULL OR finalized_tip_height >= last_finalized_height)",
    "indexer_state_default_key": "CHECK (state_key = 'default')",
    "valoper_profiles_source_height_check": "CHECK (source_height >= 1)",
    "valoper_profiles_list_position_check": "CHECK (list_position >= 0)",
    "valoper_profiles_moniker_length_check": "CHECK (char_length(moniker) >= 1 AND char_length(moniker) <= 32)",
    "valoper_profiles_description_length_check": "CHECK (octet_length(description) >= 1 AND octet_length(description) <= 2048)",
    "valoper_profiles_server_type_check": "CHECK (server_type IN ('cloud', 'on-prem', 'data-center'))",
    "valoper_profiles_operator_address_check": "CHECK (operator_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')",
    "valoper_profiles_signing_address_check": "CHECK (signing_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')",
    "valoper_profiles_signing_pubkey_check": "CHECK (signing_pubkey ~ '^gpub1[023456789acdefghjklmnpqrstuvwxyz]+$' AND (octet_length(signing_pubkey) >= 91 AND octet_length(signing_pubkey) <= 256))",
    "valopers_snapshot_state_default_key": "CHECK (state_key = 'default')",
    "valopers_snapshot_state_source_height_check": "CHECK (source_height >= 1)",
    "valopers_snapshot_state_page_count_check": "CHECK (page_count >= 0 AND page_count <= 20)",
    "valopers_snapshot_state_profile_count_check": "CHECK (profile_count >= 0 AND profile_count <= 1000)",
    "valopers_snapshot_state_counts_consistent": "CHECK ((profile_count = 0 AND page_count = 0) OR (profile_count > 0 AND page_count >= 1))",
}
EXPECTED_INDEXES = {
    "transactions_tx_hash_hex_idx": ("transactions", False, (("tx_hash_hex", "ASC"),), "tx_hash_hex IS NOT NULL"),
    "blocks_time_utc_idx": ("blocks", False, (("time_utc", "DESC"),), None),
    "validator_set_members_height_power_idx": ("validator_set_members", False, (("height", "ASC"), ("voting_power", "DESC"), ("signing_address", "ASC")), None),
    "validator_set_members_signing_height_idx": ("validator_set_members", False, (("signing_address", "ASC"), ("height", "DESC")), None),
    "validator_signatures_signing_height_status_idx": ("validator_signatures", False, (("signing_address", "ASC"), ("height", "DESC"), ("vote_status", "ASC"), ("signed", "ASC")), None),
    "validator_signatures_height_status_idx": ("validator_signatures", False, (("height", "DESC"), ("vote_status", "ASC"), ("signing_address", "ASC")), None),
    "rpc_endpoints_health_idx": ("rpc_endpoints", False, (("chain_id", "ASC"), ("is_enabled", "ASC"), ("healthy", "ASC"), ("latest_observed_height", "DESC")), None),
    "rpc_endpoints_one_selected_per_chain_idx": ("rpc_endpoints", True, (("chain_id", "ASC"),), "is_selected"),
    "rpc_endpoint_checks_endpoint_time_idx": ("rpc_endpoint_checks", False, (("rpc_endpoint_id", "ASC"), ("checked_at", "DESC")), None),
    "rpc_endpoint_checks_chain_selected_time_idx": ("rpc_endpoint_checks", False, (("chain_id", "ASC"), ("selected_for_cycle", "ASC"), ("checked_at", "DESC")), None),
    "valoper_profiles_list_position_idx": ("valoper_profiles", False, (("list_position", "ASC"), ("operator_address", "ASC")), None),
    "valoper_profiles_moniker_idx": ("valoper_profiles", False, (("moniker", "ASC"), ("operator_address", "ASC")), None),
}

# Network-distribution schema is part of the final (0003) catalog only. Historical migration
# tools retain their own stage-specific expectations.
EXPECTED_TABLES.update({"network_distribution_geo_cache", "network_distribution_snapshots", "network_distribution_snapshot_sources"})
EXPECTED_COLUMNS.update({
 "network_distribution_geo_cache": {
  "ip": ("inet","NO","",None), "lookup_success": ("boolean","NO","",None), "continent_name": ("text","YES","",None), "country_code": ("text","YES","",None), "country_name": ("text","YES","",None), "region_name": ("text","YES","",None), "asn": ("bigint","YES","",None), "provider_name": ("text","YES","",None), "lookup_provider": ("text","NO","",None), "fetched_at": ("timestamp with time zone","NO","",None), "expires_at": ("timestamp with time zone","NO","",None), "error_code": ("text","YES","",None), "inserted_at": ("timestamp with time zone","NO","","now()"), "updated_at": ("timestamp with time zone","NO","","now()")},
 "network_distribution_snapshots": {
  "id": ("bigint","NO","a",None), "chain_id": ("text","NO","",None), "source_kind": ("text","NO","",None), "scanned_at": ("timestamp with time zone","NO","",None), "rpc_sources_total": ("integer","NO","",None), "rpc_sources_ok": ("integer","NO","",None), "visible_node_ids": ("integer","NO","",None), "unique_public_ips": ("integer","NO","",None), "geolocated_node_ids": ("integer","NO","",None), "geolocated_public_ips": ("integer","NO","",None), "node_id_ip_conflicts": ("integer","NO","","0"), "region_count": ("integer","NO","",None), "country_count": ("integer","NO","",None), "provider_count": ("integer","NO","",None), "regions": ("jsonb","NO","",None), "countries": ("jsonb","NO","",None), "providers": ("jsonb","NO","",None), "inserted_at": ("timestamp with time zone","NO","","now()")},
 "network_distribution_snapshot_sources": {
  "snapshot_id": ("bigint","NO","",None), "source_order": ("integer","NO","",None), "rpc_endpoint_id": ("bigint","YES","",None), "success": ("boolean","NO","",None), "reported_peer_count": ("integer","YES","",None), "accepted_peer_count": ("integer","NO","","0"), "duration_ms": ("integer","YES","",None), "error_code": ("text","YES","",None), "inserted_at": ("timestamp with time zone","NO","","now()")}})
EXPECTED_PRIMARY_KEYS.update({"network_distribution_geo_cache": ("ip",), "network_distribution_snapshots": ("id",), "network_distribution_snapshot_sources": ("snapshot_id","source_order")})
EXPECTED_FOREIGN_KEYS.update({
 ("network_distribution_snapshot_sources", ("snapshot_id",), "network_distribution_snapshots", ("id",), "c"),
 ("network_distribution_snapshot_sources", ("rpc_endpoint_id",), "rpc_endpoints", ("id",), "n")})
EXPECTED_CHECKS.update({
 "network_distribution_geo_cache_country_code_check": "CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$')",
 "network_distribution_geo_cache_asn_check": "CHECK (asn IS NULL OR asn > 0)",
 "network_distribution_geo_cache_provider_name_check": "CHECK (provider_name IS NULL OR char_length(provider_name) <= 255)",
 "network_distribution_geo_cache_error_code_check": "CHECK (error_code IS NULL OR char_length(error_code) <= 64)",
 "network_distribution_geo_cache_expiry_check": "CHECK (expires_at >= fetched_at)",
 "network_distribution_geo_cache_continent_name_check": "CHECK (continent_name IS NULL OR char_length(continent_name) <= 128)",
 "network_distribution_geo_cache_country_name_check": "CHECK (country_name IS NULL OR char_length(country_name) <= 128)",
 "network_distribution_geo_cache_region_name_check": "CHECK (region_name IS NULL OR char_length(region_name) <= 255)",
 "network_distribution_geo_cache_lookup_provider_check": "CHECK (char_length(lookup_provider) >= 1 AND char_length(lookup_provider) <= 128)",
 "network_distribution_geo_cache_state_check": "CHECK ((lookup_success AND error_code IS NULL) OR (NOT lookup_success AND error_code IS NOT NULL AND continent_name IS NULL AND country_code IS NULL AND country_name IS NULL AND region_name IS NULL AND asn IS NULL AND provider_name IS NULL))",
 "network_distribution_snapshots_counts_check": "CHECK (rpc_sources_total >= 0 AND rpc_sources_ok >= 0 AND visible_node_ids >= 0 AND unique_public_ips >= 0 AND geolocated_node_ids >= 0 AND geolocated_public_ips >= 0 AND node_id_ip_conflicts >= 0 AND region_count >= 0 AND country_count >= 0 AND provider_count >= 0 AND rpc_sources_ok <= rpc_sources_total AND geolocated_node_ids <= visible_node_ids AND geolocated_public_ips <= unique_public_ips)",
 "network_distribution_snapshots_arrays_check": "CHECK (jsonb_typeof(regions) = 'array' AND jsonb_typeof(countries) = 'array' AND jsonb_typeof(providers) = 'array')",
 "network_distribution_snapshot_sources_values_check": "CHECK (source_order >= 0 AND (reported_peer_count IS NULL OR reported_peer_count >= 0) AND accepted_peer_count >= 0 AND (duration_ms IS NULL OR duration_ms >= 0) AND (error_code IS NULL OR char_length(error_code) <= 64))",
 "network_distribution_snapshot_sources_state_check": "CHECK ((success AND error_code IS NULL) OR (NOT success AND error_code IS NOT NULL))"})
EXPECTED_INDEXES.update({
 "network_distribution_geo_cache_expires_idx": ("network_distribution_geo_cache",False,(("expires_at","ASC"),),None),
 "network_distribution_geo_cache_country_idx": ("network_distribution_geo_cache",False,(("country_code","ASC"),),"lookup_success AND country_code IS NOT NULL"),
 "network_distribution_geo_cache_asn_idx": ("network_distribution_geo_cache",False,(("asn","ASC"),("provider_name","ASC")),"lookup_success AND asn IS NOT NULL"),
 "network_distribution_snapshots_chain_latest_idx": ("network_distribution_snapshots",False,(("chain_id","ASC"),("scanned_at","DESC"),("id","DESC")),None)})


def schema_expectations(*, excluded_tables: set[str] | None = None,
                        include_transaction_hash: bool = True) -> dict[str, Any]:
    """Derive an exact historical stage without mutating final expectations."""
    excluded_tables = excluded_tables or set()
    result = {
        "tables": EXPECTED_TABLES - excluded_tables,
        "columns": {name: copy.deepcopy(value) for name, value in EXPECTED_COLUMNS.items() if name not in excluded_tables},
        "primary_keys": {name: value for name, value in EXPECTED_PRIMARY_KEYS.items() if name not in excluded_tables},
        "unique_constraints": {value for value in EXPECTED_UNIQUES if value[0] not in excluded_tables},
        "foreign_keys": {value for value in EXPECTED_FOREIGN_KEYS if value[0] not in excluded_tables and value[2] not in excluded_tables},
        "check_constraints": {name: value for name, value in EXPECTED_CHECKS.items()
                              if not any(name.startswith(f"{table}_") for table in excluded_tables)},
        "indexes": {name: value for name, value in EXPECTED_INDEXES.items() if value[0] not in excluded_tables},
    }
    if not include_transaction_hash:
        result["columns"]["transactions"].pop("tx_hash_hex")
        for name in {"transactions_tx_hash_hex_format", "transactions_tx_hash_consistent"}:
            result["check_constraints"].pop(name)
        result["indexes"].pop("transactions_tx_hash_hex_idx")
    return result


# Governance is the final (0004) catalog; the previous final catalog remains the
# exact source stage accepted by the explicit governance migration.
PRE_GOVERNANCE_SCHEMA_EXPECTATIONS = schema_expectations()
GOVERNANCE_TABLES = {"governance_proposals", "governance_votes", "governance_sync_state"}
EXPECTED_TABLES.update(GOVERNANCE_TABLES)
EXPECTED_COLUMNS.update({
 "governance_proposals": {
  "chain_id": ("text","NO","",None), "realm_path": ("text","NO","",None), "proposal_id": ("bigint","NO","",None), "title": ("text","NO","",None), "author_display": ("text","YES","",None), "author_address": ("text","YES","",None), "status": ("text","NO","",None), "eligible_tiers": ("jsonb","NO","",None), "description": ("text","NO","",None), "executor_text": ("text","YES","",None), "executor_creation_realm": ("text","YES","",None), "rejection_reason": ("text","YES","",None), "yes_percent": ("numeric(7,4)","YES","",None), "no_percent": ("numeric(7,4)","YES","",None), "abstain_percent": ("numeric(7,4)","YES","",None), "detail_parse_status": ("text","NO","",None), "votes_parse_status": ("text","NO","",None), "parse_warnings": ("jsonb","NO","",None), "raw_detail_render": ("text","YES","",None), "raw_votes_render": ("text","YES","",None), "first_observed_height": ("bigint","NO","",None), "last_observed_height": ("bigint","NO","",None), "first_observed_at": ("timestamp with time zone","NO","","now()"), "last_observed_at": ("timestamp with time zone","NO","","now()"), "inserted_at": ("timestamp with time zone","NO","","now()"), "updated_at": ("timestamp with time zone","NO","","now()")},
 "governance_votes": {
  "chain_id": ("text","NO","",None), "realm_path": ("text","NO","",None), "proposal_id": ("bigint","NO","",None), "voter_key": ("text","NO","",None), "voter_display": ("text","NO","",None), "voter_address": ("text","YES","",None), "option": ("text","NO","",None), "tier": ("text","NO","",None), "voting_power": ("numeric(78,0)","NO","",None), "first_observed_height": ("bigint","NO","",None), "last_observed_height": ("bigint","NO","",None), "first_observed_at": ("timestamp with time zone","NO","","now()"), "last_observed_at": ("timestamp with time zone","NO","","now()"), "inserted_at": ("timestamp with time zone","NO","","now()"), "updated_at": ("timestamp with time zone","NO","","now()")},
 "governance_sync_state": {
  "chain_id": ("text","NO","",None), "realm_path": ("text","NO","",None), "source_height": ("bigint","NO","",None), "page_count": ("integer","NO","",None), "proposal_count": ("integer","NO","",None), "first_proposal_id": ("bigint","YES","",None), "latest_proposal_id": ("bigint","YES","",None), "last_success_at": ("timestamp with time zone","NO","","now()"), "updated_at": ("timestamp with time zone","NO","","now()")}})
EXPECTED_PRIMARY_KEYS.update({"governance_proposals": ("chain_id","realm_path","proposal_id"), "governance_votes": ("chain_id","realm_path","proposal_id","voter_key"), "governance_sync_state": ("chain_id","realm_path")})
EXPECTED_FOREIGN_KEYS.add(("governance_votes",("chain_id","realm_path","proposal_id"),"governance_proposals",("chain_id","realm_path","proposal_id"),"c"))
EXPECTED_CHECKS.update({
 "governance_proposals_chain_id_check": "CHECK (char_length(chain_id) BETWEEN 1 AND 128)", "governance_proposals_realm_path_check": "CHECK (char_length(realm_path) BETWEEN 1 AND 512)", "governance_proposals_proposal_id_check": "CHECK (proposal_id >= 0)", "governance_proposals_title_check": "CHECK (char_length(title) BETWEEN 1 AND 1000)", "governance_proposals_author_display_check": "CHECK (author_display IS NULL OR char_length(author_display) <= 1000)", "governance_proposals_author_address_check": "CHECK (author_address IS NULL OR author_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')", "governance_proposals_status_check": "CHECK (status IN ('ACTIVE', 'ACCEPTED', 'REJECTED', 'UNKNOWN'))", "governance_proposals_eligible_tiers_check": "CHECK (jsonb_typeof(eligible_tiers) = 'array')", "governance_proposals_description_check": "CHECK (char_length(description) <= 100000)", "governance_proposals_executor_text_check": "CHECK (executor_text IS NULL OR char_length(executor_text) <= 100000)", "governance_proposals_executor_creation_realm_check": "CHECK (executor_creation_realm IS NULL OR char_length(executor_creation_realm) <= 1000)", "governance_proposals_rejection_reason_check": "CHECK (rejection_reason IS NULL OR char_length(rejection_reason) <= 10000)", "governance_proposals_detail_parse_status_check": "CHECK (detail_parse_status IN ('parsed', 'partial'))", "governance_proposals_votes_parse_status_check": "CHECK (votes_parse_status IN ('parsed', 'empty', 'unparsed'))", "governance_proposals_parse_warnings_check": "CHECK (jsonb_typeof(parse_warnings) = 'array')", "governance_proposals_percentages_check": "CHECK ((yes_percent IS NULL OR yes_percent BETWEEN 0 AND 100) AND (no_percent IS NULL OR no_percent BETWEEN 0 AND 100) AND (abstain_percent IS NULL OR abstain_percent BETWEEN 0 AND 100))", "governance_proposals_raw_size_check": "CHECK ((raw_detail_render IS NULL OR octet_length(raw_detail_render) <= 1048576) AND (raw_votes_render IS NULL OR octet_length(raw_votes_render) <= 1048576))", "governance_proposals_heights_check": "CHECK (first_observed_height >= 1 AND last_observed_height >= first_observed_height)", "governance_proposals_times_check": "CHECK (last_observed_at >= first_observed_at)",
 "governance_votes_voter_key_check": "CHECK (char_length(voter_key) BETWEEN 1 AND 1100)", "governance_votes_voter_display_check": "CHECK (char_length(voter_display) BETWEEN 1 AND 1000)", "governance_votes_voter_address_check": "CHECK (voter_address IS NULL OR voter_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')", "governance_votes_option_check": "CHECK (option IN ('YES', 'NO', 'ABSTAIN'))", "governance_votes_tier_check": "CHECK (char_length(tier) BETWEEN 1 AND 64)", "governance_votes_voting_power_check": "CHECK (voting_power >= 0)", "governance_votes_heights_check": "CHECK (first_observed_height >= 1 AND last_observed_height >= first_observed_height)", "governance_votes_times_check": "CHECK (last_observed_at >= first_observed_at)",
 "governance_sync_state_chain_id_check": "CHECK (char_length(chain_id) BETWEEN 1 AND 128)", "governance_sync_state_realm_path_check": "CHECK (char_length(realm_path) BETWEEN 1 AND 512)", "governance_sync_state_source_height_check": "CHECK (source_height >= 1)", "governance_sync_state_page_count_check": "CHECK (page_count BETWEEN 1 AND 100)", "governance_sync_state_proposal_count_check": "CHECK (proposal_count BETWEEN 0 AND 1000)", "governance_sync_state_counts_check": "CHECK ((proposal_count = 0 AND first_proposal_id IS NULL AND latest_proposal_id IS NULL AND page_count >= 1) OR (proposal_count > 0 AND first_proposal_id IS NOT NULL AND latest_proposal_id IS NOT NULL AND first_proposal_id >= 0 AND latest_proposal_id >= first_proposal_id AND page_count >= 1))"})
EXPECTED_INDEXES.update({"governance_proposals_realm_id_idx": ("governance_proposals",False,(("chain_id","ASC"),("realm_path","ASC"),("proposal_id","DESC")),None), "governance_proposals_realm_status_id_idx": ("governance_proposals",False,(("chain_id","ASC"),("realm_path","ASC"),("status","ASC"),("proposal_id","DESC")),None), "governance_votes_voter_address_idx": ("governance_votes",False,(("voter_address","ASC"),),"voter_address IS NOT NULL")})
PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS = schema_expectations()

TRANSACTION_PARTICIPANT_TABLE = "transaction_participants"
EXPECTED_TABLES.add(TRANSACTION_PARTICIPANT_TABLE)
EXPECTED_COLUMNS[TRANSACTION_PARTICIPANT_TABLE] = {
    "block_height": ("bigint", "NO", "", None),
    "tx_index": ("integer", "NO", "", None),
    "message_index": ("integer", "NO", "", None),
    "role": ("text", "NO", "", None),
    "address": ("text", "NO", "", None),
    "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
}
EXPECTED_PRIMARY_KEYS[TRANSACTION_PARTICIPANT_TABLE] = (
    "block_height", "tx_index", "message_index", "role", "address",
)
EXPECTED_FOREIGN_KEYS.add((
    TRANSACTION_PARTICIPANT_TABLE, ("block_height", "tx_index"),
    "transactions", ("block_height", "tx_index"), "c",
))
EXPECTED_CHECKS.update({
    "transaction_participants_block_height_check": "CHECK (block_height > 0)",
    "transaction_participants_tx_index_check": "CHECK (tx_index >= 0)",
    "transaction_participants_message_index_check": "CHECK (message_index BETWEEN 0 AND 19)",
    "transaction_participants_role_check": "CHECK (role IN ('sender', 'recipient'))",
    "transaction_participants_address_check": (
        "CHECK (char_length(address) = 40 AND "
        "address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')"
    ),
})
EXPECTED_INDEXES["transaction_participants_address_position_idx"] = (
    TRANSACTION_PARTICIPANT_TABLE, False,
    (("address", "ASC"), ("block_height", "DESC"), ("tx_index", "DESC")), None,
)
PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS = schema_expectations()
TRANSACTION_EXECUTION_RESULT_TABLE = "transaction_execution_results"
EXPECTED_TABLES.add(TRANSACTION_EXECUTION_RESULT_TABLE)
EXPECTED_COLUMNS[TRANSACTION_EXECUTION_RESULT_TABLE] = {
    "block_height": ("bigint", "NO", "", None),
    "tx_index": ("integer", "NO", "", None),
    "execution_status": ("text", "NO", "", None),
    "gas_wanted": ("numeric(78,0)", "NO", "", None),
    "gas_used": ("numeric(78,0)", "NO", "", None),
    "error_text": ("text", "YES", "", None),
    "log_text": ("text", "YES", "", None),
    "info_text": ("text", "YES", "", None),
    "data_base64": ("text", "YES", "", None),
    "events": ("jsonb", "YES", "", None),
    "raw_result": ("jsonb", "YES", "", None),
    "source_rpc_endpoint_id": ("bigint", "YES", "", None),
    "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    "updated_at": ("timestamp with time zone", "NO", "", "now()"),
}
EXPECTED_PRIMARY_KEYS[TRANSACTION_EXECUTION_RESULT_TABLE] = ("block_height", "tx_index")
EXPECTED_FOREIGN_KEYS.update({
    (TRANSACTION_EXECUTION_RESULT_TABLE, ("block_height", "tx_index"),
     "transactions", ("block_height", "tx_index"), "c"),
    (TRANSACTION_EXECUTION_RESULT_TABLE, ("source_rpc_endpoint_id",),
     "rpc_endpoints", ("id",), "n"),
})
EXPECTED_CHECKS.update({
    "transaction_execution_results_status_check": "CHECK (execution_status IN ('success', 'failed'))",
    "transaction_execution_results_gas_wanted_check": "CHECK (gas_wanted >= 0)",
    "transaction_execution_results_gas_used_check": "CHECK (gas_used >= 0)",
    "transaction_execution_results_error_check": (
        "CHECK ((execution_status = 'success' AND error_text IS NULL) OR "
        "(execution_status = 'failed' AND error_text IS NOT NULL AND btrim(error_text) <> ''))"
    ),
})
EXPECTED_TABLE_PRIVILEGES = {
    "utsa_gno_api": {
        TRANSACTION_PARTICIPANT_TABLE: {"SELECT"},
        TRANSACTION_EXECUTION_RESULT_TABLE: {"SELECT"},
    },
    "utsa_gno_indexer": {
        TRANSACTION_PARTICIPANT_TABLE: {"SELECT", "INSERT", "DELETE"},
        TRANSACTION_EXECUTION_RESULT_TABLE: {"SELECT", "INSERT", "UPDATE"},
    },
}
PRE_REALM_CATALOG_EXPECTATIONS = schema_expectations()
EXPECTED_TABLES.update({"realm_catalog", "realm_catalog_state"})
EXPECTED_COLUMNS["realm_catalog"] = {
 "chain_id":("text","NO","",None),"path":("text","NO","",None),"path_kind":("text","NO","",None),
 "seen_via_rpc":("boolean","NO","","false"),"seen_via_transactions":("boolean","NO","","false"),"rpc_visible":("boolean","NO","","false"),
 "deployer_address":("text","YES","",None),"deploy_height":("bigint","YES","",None),"deploy_tx_index":("integer","YES","",None),
 "first_seen_height":("bigint","YES","",None),"last_activity_height":("bigint","YES","",None),"last_activity_tx_index":("integer","YES","",None),
 "last_activity_at":("timestamp with time zone","YES","",None),"call_count":("bigint","NO","","0"),
 "successful_call_count":("bigint","NO","","0"),"failed_call_count":("bigint","NO","","0"),"unknown_result_call_count":("bigint","NO","","0"),
 "last_counted_height":("bigint","YES","",None),"first_discovered_at":("timestamp with time zone","NO","","now()"),
 "last_rpc_seen_at":("timestamp with time zone","YES","",None),"inserted_at":("timestamp with time zone","NO","","now()"),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_COLUMNS["realm_catalog_state"]={"chain_id":("text","NO","",None),"observed_height":("bigint","NO","",None),"rpc_path_count":("integer","NO","",None),"activity_from_height":("bigint","YES","",None),"activity_through_height":("bigint","YES","",None),"source_rpc_endpoint_id":("bigint","YES","",None),"refreshed_at":("timestamp with time zone","NO","",None),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_PRIMARY_KEYS.update({"realm_catalog":("chain_id","path"),"realm_catalog_state":("chain_id",)})
EXPECTED_FOREIGN_KEYS.add(("realm_catalog_state",("source_rpc_endpoint_id",),"rpc_endpoints",("id",),"n"))
EXPECTED_CHECKS.update({
 "realm_catalog_path_kind_check":"CHECK (path_kind IN ('realm', 'package'))",
 "realm_catalog_path_check":"CHECK ((char_length(path) >= 1 AND char_length(path) <= 256) AND path ~ '^gno\\.land/[rp]/[!-\\.0-~]+(/[!-\\.0-~]+)*$' AND path !~ '[?#]' AND ((path_kind = 'realm' AND path ~~ 'gno.land/r/%') OR (path_kind = 'package' AND path ~~ 'gno.land/p/%')))",
 "realm_catalog_deployer_check":"CHECK (deployer_address IS NULL OR deployer_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')",
 "realm_catalog_deploy_position_check":"CHECK ((deploy_height IS NULL) = (deploy_tx_index IS NULL) AND (deploy_height IS NULL OR (deploy_height > 0 AND deploy_tx_index >= 0)))",
 "realm_catalog_activity_position_check":"CHECK ((last_activity_height IS NULL) = (last_activity_tx_index IS NULL) AND (last_activity_height IS NULL) = (last_activity_at IS NULL) AND (last_activity_height IS NULL OR (last_activity_height > 0 AND last_activity_tx_index >= 0)))",
 "realm_catalog_counters_check":"CHECK (call_count >= 0 AND successful_call_count >= 0 AND failed_call_count >= 0 AND unknown_result_call_count >= 0 AND successful_call_count + failed_call_count + unknown_result_call_count = call_count)",
 "realm_catalog_counted_height_check":"CHECK ((call_count = 0 AND last_counted_height IS NULL) OR (call_count > 0 AND last_counted_height IS NOT NULL AND last_counted_height > 0))",
 "realm_catalog_first_seen_check":"CHECK (first_seen_height IS NULL OR first_seen_height > 0)",
 "realm_catalog_rpc_visibility_check":"CHECK (NOT rpc_visible OR seen_via_rpc)",
 "realm_catalog_rpc_seen_at_check":"CHECK ((NOT seen_via_rpc AND last_rpc_seen_at IS NULL) OR (seen_via_rpc AND last_rpc_seen_at IS NOT NULL))",
 "realm_catalog_transaction_metadata_check":"CHECK (seen_via_transactions OR (deployer_address IS NULL AND deploy_height IS NULL AND first_seen_height IS NULL AND last_activity_height IS NULL AND call_count = 0))",
 "realm_catalog_state_observed_height_check":"CHECK (observed_height > 0)","realm_catalog_state_path_count_check":"CHECK (rpc_path_count BETWEEN 0 AND 10000)",
 "realm_catalog_state_activity_range_check":"CHECK ((activity_from_height IS NULL AND activity_through_height IS NULL) OR (activity_from_height > 0 AND activity_through_height >= activity_from_height))"})
EXPECTED_INDEXES.update({"realm_catalog_kind_path_idx":("realm_catalog",False,(("chain_id","ASC"),("path_kind","ASC"),("path","ASC")),None),"realm_catalog_visibility_idx":("realm_catalog",False,(("chain_id","ASC"),("rpc_visible","ASC"),("path_kind","ASC")),None),"realm_catalog_activity_idx":("realm_catalog",False,(("chain_id","ASC"),("last_activity_height","DESC"),("path","ASC")),None),"realm_catalog_calls_idx":("realm_catalog",False,(("chain_id","ASC"),("call_count","DESC"),("path","ASC")),None)})
EXPECTED_TABLE_PRIVILEGES["utsa_gno_api"].update({"realm_catalog":{"SELECT"},"realm_catalog_state":{"SELECT"}})
EXPECTED_TABLE_PRIVILEGES["utsa_gno_indexer"].update({"realm_catalog":{"SELECT","INSERT","UPDATE"},"realm_catalog_state":{"SELECT","INSERT","UPDATE"}})
PRE_REALM_CALL_INDEX_EXPECTATIONS = schema_expectations()
EXPECTED_TABLES.update({"realm_call_index", "realm_call_index_state"})
EXPECTED_COLUMNS["realm_call_index"] = {
 "chain_id":("text","NO","",None),"block_height":("bigint","NO","",None),"tx_index":("integer","NO","",None),"message_index":("integer","NO","",None),"path":("text","NO","",None),"caller_address":("text","YES","",None),"function_name":("text","YES","",None),"args_count":("integer","YES","",None),"send_amount":("text","YES","",None),"inserted_at":("timestamp with time zone","NO","","now()"),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_COLUMNS["realm_call_index_state"] = {"chain_id":("text","NO","",None),"from_height":("bigint","NO","",None),"through_height":("bigint","NO","",None),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_PRIMARY_KEYS.update({"realm_call_index":("chain_id","block_height","tx_index","message_index"),"realm_call_index_state":("chain_id",)})
EXPECTED_FOREIGN_KEYS.add(("realm_call_index",("block_height","tx_index"),"transactions",("block_height","tx_index"),"c"))
EXPECTED_CHECKS.update({
 "realm_call_index_chain_id_check":"CHECK (char_length(chain_id) BETWEEN 1 AND 128)","realm_call_index_block_height_check":"CHECK (block_height > 0)","realm_call_index_tx_index_check":"CHECK (tx_index >= 0)","realm_call_index_message_index_check":"CHECK (message_index BETWEEN 0 AND 19)","realm_call_index_path_check":"CHECK ((char_length(path) >= 1 AND char_length(path) <= 256) AND path ~ '^gno\\.land/r/[!-\\.0-~]+(/[!-\\.0-~]+)*$' AND path !~ '[?#]')","realm_call_index_caller_check":"CHECK (caller_address IS NULL OR caller_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$')","realm_call_index_function_check":"CHECK (function_name IS NULL OR char_length(function_name) BETWEEN 1 AND 160)","realm_call_index_args_count_check":"CHECK (args_count IS NULL OR args_count BETWEEN 0 AND 100000)","realm_call_index_send_check":"CHECK (send_amount IS NULL OR char_length(send_amount) BETWEEN 1 AND 160)","realm_call_index_state_chain_id_check":"CHECK (char_length(chain_id) BETWEEN 1 AND 128)","realm_call_index_state_from_height_check":"CHECK (from_height > 0)","realm_call_index_state_range_check":"CHECK (through_height >= from_height)"})
EXPECTED_INDEXES["realm_call_index_path_position_idx"]=("realm_call_index",False,(("chain_id","ASC"),("path","ASC"),("block_height","DESC"),("tx_index","DESC"),("message_index","DESC")),None)
EXPECTED_TABLE_PRIVILEGES["utsa_gno_api"].update({"realm_call_index":{"SELECT"},"realm_call_index_state":{"SELECT"}})
EXPECTED_TABLE_PRIVILEGES["utsa_gno_indexer"].update({"realm_call_index":{"SELECT","INSERT","UPDATE","DELETE"},"realm_call_index_state":{"SELECT","INSERT","UPDATE","DELETE"}})
PRE_REALM_METADATA_EXPECTATIONS = schema_expectations()
METADATA_TABLES = {"realm_metadata", "realm_metadata_files", "realm_metadata_imports", "realm_metadata_refresh_state"}
EXPECTED_TABLES.update(METADATA_TABLES)
EXPECTED_COLUMNS["realm_metadata"] = {
 "chain_id":("text","NO","",None),"path":("text","NO","",None),"path_kind":("text","NO","",None),"observed_height":("bigint","NO","",None),"collection_status":("text","NO","",None),"content_sha256":("text","NO","",None),"file_count":("integer","NO","",None),"gno_file_count":("integer","NO","",None),"test_file_count":("integer","NO","",None),"has_gnomod":("boolean","NO","",None),"total_file_bytes":("bigint","NO","",None),"total_file_lines":("bigint","NO","",None),"dependency_count":("integer","NO","",None),"source_rpc_endpoint_id":("bigint","YES","",None),
 "qdoc_status":("text","NO","",None),"qdoc_summary":("jsonb","YES","",None),"qdoc_last_successful_height":("bigint","YES","",None),"qdoc_payload":("jsonb","YES","",None),"qpkg_json_status":("text","NO","",None),"qpkg_json_summary":("jsonb","YES","",None),"qpkg_json_last_successful_height":("bigint","YES","",None),"qpkg_json_payload":("jsonb","YES","",None),"qfuncs_status":("text","NO","",None),"qfuncs_summary":("jsonb","YES","",None),"qfuncs_last_successful_height":("bigint","YES","",None),"qfuncs_payload":("jsonb","YES","",None),
 "qrender_status":("text","NO","",None),"qrender_last_successful_height":("bigint","YES","",None),"qrender_sha256":("text","YES","",None),"qrender_byte_count":("bigint","YES","",None),"qrender_line_count":("bigint","YES","",None),"qrender_non_empty":("boolean","YES","",None),"qstorage_status":("text","NO","",None),"qstorage_last_successful_height":("bigint","YES","",None),"qstorage_bytes":("numeric(40,0)","YES","",None),"qstorage_deposit_ugnot":("numeric(40,0)","YES","",None),"collected_at":("timestamp with time zone","NO","",None),"inserted_at":("timestamp with time zone","NO","","now()"),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_COLUMNS["realm_metadata_files"]={"chain_id":("text","NO","",None),"path":("text","NO","",None),"filename":("text","NO","",None),"file_kind":("text","NO","",None),"content":("text","NO","",None),"byte_count":("integer","NO","",None),"line_count":("integer","NO","",None),"sha256":("text","NO","",None),"package_declared":("boolean","NO","",None),"import_candidate_count":("integer","NO","",None),"inserted_at":("timestamp with time zone","NO","","now()"),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_COLUMNS["realm_metadata_imports"]={"chain_id":("text","NO","",None),"path":("text","NO","",None),"source_filename":("text","NO","",None),"imported_path":("text","NO","",None),"imported_kind":("text","NO","",None)}
EXPECTED_COLUMNS["realm_metadata_refresh_state"]={"chain_id":("text","NO","",None),"observed_height":("bigint","NO","",None),"run_status":("text","NO","",None),"selected_path_count":("integer","NO","",None),"published_path_count":("integer","NO","",None),"failed_path_count":("integer","NO","",None),"started_at":("timestamp with time zone","NO","",None),"completed_at":("timestamp with time zone","YES","",None),"last_successful_height":("bigint","YES","",None),"last_successful_at":("timestamp with time zone","YES","",None),"updated_at":("timestamp with time zone","NO","","now()")}
EXPECTED_PRIMARY_KEYS.update({"realm_metadata":("chain_id","path"),"realm_metadata_files":("chain_id","path","filename"),"realm_metadata_imports":("chain_id","path","source_filename","imported_path"),"realm_metadata_refresh_state":("chain_id",)})
EXPECTED_FOREIGN_KEYS.update({("realm_metadata",("chain_id","path"),"realm_catalog",("chain_id","path"),"c"),("realm_metadata",("source_rpc_endpoint_id",),"rpc_endpoints",("id",),"n"),("realm_metadata_files",("chain_id","path"),"realm_metadata",("chain_id","path"),"c"),("realm_metadata_imports",("chain_id","path","source_filename"),"realm_metadata_files",("chain_id","path","filename"),"c")})
EXPECTED_INDEXES.update({"realm_metadata_imports_source_idx":("realm_metadata_imports",False,(("chain_id","ASC"),("path","ASC")),None),"realm_metadata_imports_reverse_idx":("realm_metadata_imports",False,(("chain_id","ASC"),("imported_path","ASC")),None)})
# Every named metadata CHECK is part of the fail-closed contract. Expressions are
# populated from the migration to keep this declaration adjacent to its table shape.
EXPECTED_CHECKS.update({
 "realm_metadata_chain_id_check":"CHECK (char_length(chain_id) BETWEEN 1 AND 128)","realm_metadata_path_kind_check":"CHECK (path_kind IN ('realm', 'package'))","realm_metadata_path_check":"CHECK ((char_length(path) >= 1 AND char_length(path) <= 256) AND path ~ '^gno\\.land/[rp]/[!-\\.0-~]+(/[!-\\.0-~]+)*$' AND path !~ '[?#]' AND ((path_kind = 'realm' AND path ~~ 'gno.land/r/%') OR (path_kind = 'package' AND path ~~ 'gno.land/p/%')))","realm_metadata_height_check":"CHECK (observed_height > 0)","realm_metadata_collection_status_check":"CHECK (collection_status IN ('complete', 'partial'))","realm_metadata_sha256_check":"CHECK (content_sha256 ~ '^[0-9a-f]{64}$')",
 "realm_metadata_counts_check":"CHECK (file_count BETWEEN 0 AND 256 AND gno_file_count BETWEEN 0 AND file_count AND test_file_count BETWEEN 0 AND gno_file_count AND total_file_bytes BETWEEN 0 AND 8388608 AND total_file_lines >= 0 AND dependency_count >= 0)",
 "realm_metadata_capability_status_check":"CHECK (qdoc_status IN ('ok', 'not_applicable', 'application_error', 'rpc_error', 'invalid_response') AND qpkg_json_status IN ('ok', 'not_applicable', 'application_error', 'rpc_error', 'invalid_response') AND qfuncs_status IN ('ok', 'not_applicable', 'application_error', 'rpc_error', 'invalid_response') AND qrender_status IN ('ok', 'not_applicable', 'application_error', 'rpc_error', 'invalid_response') AND qstorage_status IN ('ok', 'not_applicable', 'application_error', 'rpc_error', 'invalid_response'))",
 "realm_metadata_json_types_check":"CHECK ((qdoc_summary IS NULL OR jsonb_typeof(qdoc_summary) = 'object') AND (qpkg_json_summary IS NULL OR jsonb_typeof(qpkg_json_summary) = 'object') AND (qfuncs_summary IS NULL OR jsonb_typeof(qfuncs_summary) = 'object') AND (qdoc_payload IS NULL OR jsonb_typeof(qdoc_payload) IN ('object', 'array')) AND (qpkg_json_payload IS NULL OR jsonb_typeof(qpkg_json_payload) IN ('object', 'array')) AND (qfuncs_payload IS NULL OR jsonb_typeof(qfuncs_payload) IN ('object', 'array')))",
 "realm_metadata_success_heights_check":"CHECK ((qdoc_last_successful_height IS NULL OR qdoc_last_successful_height > 0) AND (qpkg_json_last_successful_height IS NULL OR qpkg_json_last_successful_height > 0) AND (qfuncs_last_successful_height IS NULL OR qfuncs_last_successful_height > 0) AND (qrender_last_successful_height IS NULL OR qrender_last_successful_height > 0) AND (qstorage_last_successful_height IS NULL OR qstorage_last_successful_height > 0))","realm_metadata_qrender_check":"CHECK ((qrender_sha256 IS NULL OR qrender_sha256 ~ '^[0-9a-f]{64}$') AND (qrender_byte_count IS NULL OR qrender_byte_count >= 0) AND (qrender_line_count IS NULL OR qrender_line_count >= 0))","realm_metadata_qstorage_check":"CHECK ((qstorage_bytes IS NULL OR qstorage_bytes >= 0) AND (qstorage_deposit_ugnot IS NULL OR qstorage_deposit_ugnot >= 0))","realm_metadata_package_capabilities_check":"CHECK (path_kind <> 'package' OR qrender_status = 'not_applicable' AND qstorage_status = 'not_applicable')",
 "realm_metadata_files_filename_check":"CHECK (char_length(filename) BETWEEN 1 AND 160 AND filename !~ '^/' AND filename !~ '^[A-Za-z]:/' AND filename !~ '\\\\' AND filename !~ '[[:cntrl:]]' AND filename !~ '(^|/)(\\.|\\.\\.|)(/|$)')","realm_metadata_files_kind_check":"CHECK (file_kind IN ('gno_source', 'gno_test', 'gnomod', 'other'))","realm_metadata_files_size_check":"CHECK (byte_count BETWEEN 0 AND 1048576 AND octet_length(content) = byte_count AND line_count BETWEEN 0 AND 100000)","realm_metadata_files_sha256_check":"CHECK (sha256 ~ '^[0-9a-f]{64}$')","realm_metadata_files_import_count_check":"CHECK (import_candidate_count BETWEEN 0 AND 1000)","realm_metadata_imports_kind_check":"CHECK (imported_kind IN ('realm', 'package'))",
 "realm_metadata_imports_path_check":"CHECK ((char_length(imported_path) >= 1 AND char_length(imported_path) <= 256) AND imported_path ~ '^gno\\.land/[rp]/[!-\\.0-~]+(/[!-\\.0-~]+)*$' AND imported_path !~ '[?#]' AND ((imported_kind = 'realm' AND imported_path ~~ 'gno.land/r/%') OR (imported_kind = 'package' AND imported_path ~~ 'gno.land/p/%')))","realm_metadata_refresh_state_chain_id_check":"CHECK (char_length(chain_id) BETWEEN 1 AND 128)","realm_metadata_refresh_state_height_check":"CHECK (observed_height > 0)","realm_metadata_refresh_state_status_check":"CHECK (run_status IN ('running', 'complete', 'partial', 'failed'))","realm_metadata_refresh_state_counts_check":"CHECK (selected_path_count >= 0 AND published_path_count >= 0 AND failed_path_count >= 0 AND published_path_count + failed_path_count <= selected_path_count)","realm_metadata_refresh_state_completion_check":"CHECK ((run_status = 'running' AND completed_at IS NULL) OR (run_status <> 'running' AND completed_at IS NOT NULL))","realm_metadata_refresh_state_success_check":"CHECK ((last_successful_height IS NULL) = (last_successful_at IS NULL) AND (last_successful_height IS NULL OR last_successful_height > 0))"})
for metadata_table in METADATA_TABLES:
    EXPECTED_TABLE_PRIVILEGES["utsa_gno_api"][metadata_table] = set()
    EXPECTED_TABLE_PRIVILEGES["utsa_gno_indexer"][metadata_table] = {"SELECT","INSERT","UPDATE","DELETE"}
FINAL_SCHEMA_EXPECTATIONS = schema_expectations()

NETWORK_DISTRIBUTION_TABLES = {
    "network_distribution_geo_cache",
    "network_distribution_snapshots",
    "network_distribution_snapshot_sources",
}
VALOPERS_TABLES = {"valoper_profiles", "valopers_snapshot_state"}
TRANSACTION_HASH_COLUMN = "tx_hash_hex"
TRANSACTION_HASH_CHECKS = {"transactions_tx_hash_hex_format", "transactions_tx_hash_consistent"}
TRANSACTION_HASH_INDEXES = {"transactions_tx_hash_hex_idx"}



LATE_TRANSACTION_TABLES = {TRANSACTION_PARTICIPANT_TABLE, TRANSACTION_EXECUTION_RESULT_TABLE,
                           "realm_catalog", "realm_catalog_state", "realm_call_index", "realm_call_index_state"} | METADATA_TABLES
PRE_NETWORK_DISTRIBUTION_EXPECTATIONS = schema_expectations(excluded_tables=NETWORK_DISTRIBUTION_TABLES | GOVERNANCE_TABLES | LATE_TRANSACTION_TABLES)
VALOPERS_ONLY_EXPECTATIONS = schema_expectations(
    excluded_tables=NETWORK_DISTRIBUTION_TABLES | GOVERNANCE_TABLES | LATE_TRANSACTION_TABLES, include_transaction_hash=False)
TRANSACTION_HASH_ONLY_EXPECTATIONS = schema_expectations(
    excluded_tables=NETWORK_DISTRIBUTION_TABLES | VALOPERS_TABLES | GOVERNANCE_TABLES | LATE_TRANSACTION_TABLES)
BASE_LEGACY_EXPECTATIONS = schema_expectations(
    excluded_tables=NETWORK_DISTRIBUTION_TABLES | VALOPERS_TABLES | GOVERNANCE_TABLES | LATE_TRANSACTION_TABLES,
    include_transaction_hash=False)


class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing schema is not compatible with the expected explorer schema."""


def migration_body_for_outer_transaction(sql: str) -> str:
    """Remove an additive migration's strict transaction envelope.

    This is deliberately not a general SQL parser. Dollar-quoted procedural blocks are
    opaque, while top-level transaction-control statements must occupy their own line.
    """
    without_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    lines = [re.sub(r"--.*$", "", line).strip() for line in without_comments.splitlines()]
    executable = [line for line in lines if line]
    if len(executable) < 3 or executable[0].upper() != "BEGIN;":
        raise SchemaCompatibilityError("additive migration must start with BEGIN")
    if executable[-1].upper() != "COMMIT;":
        raise SchemaCompatibilityError("additive migration must end with COMMIT")
    body_lines = executable[1:-1]
    dollar_quote: str | None = None
    control = re.compile(
        r"\b(?:BEGIN|START\s+TRANSACTION|COMMIT|ROLLBACK|SAVEPOINT|"
        r"RELEASE\s+SAVEPOINT|PREPARE\s+TRANSACTION)\b",
        re.IGNORECASE,
    )
    dollar_token = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
    for line in body_lines:
        position = 0
        for match in dollar_token.finditer(line):
            if dollar_quote is None and control.search(line[position:match.start()]):
                raise SchemaCompatibilityError("additive migration contains transaction control")
            token = match.group(0)
            if dollar_quote is None:
                dollar_quote = token
            elif token == dollar_quote:
                dollar_quote = None
            position = match.end()
        if dollar_quote is None and control.search(line[position:]):
            raise SchemaCompatibilityError("additive migration contains transaction control")
    if dollar_quote is not None:
        raise SchemaCompatibilityError("additive migration has an unterminated dollar quote")
    return "\n".join(body_lines) + "\n"


def _is_wrapped(value: str) -> bool:
    if not (value.startswith("(") and value.endswith(")")):
        return False
    depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(value) - 1:
                return False
    return depth == 0


def _strip_outer_parentheses(value: str) -> str:
    while _is_wrapped(value):
        value = value[1:-1].strip()
    return value


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _find_matching_parenthesis(value: str, start: int) -> int | None:
    depth = 0
    in_quote = False
    index = start
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return None


def _has_top_level_boolean_operator(value: str) -> bool:
    in_quote = False
    depth = 0
    index = 0
    lowered = value.lower()
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif depth == 0:
                if lowered.startswith("and", index) or lowered.startswith("or", index):
                    before = lowered[index - 1] if index > 0 else " "
                    after_index = index + (3 if lowered.startswith("and", index) else 2)
                    after = lowered[after_index] if after_index < len(value) else " "
                    if not _is_identifier_char(before) and not _is_identifier_char(after):
                        return True
        index += 1
    return False


def _has_top_level_comma(value: str) -> bool:
    in_quote = False
    depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                return True
        index += 1
    return False


def _can_remove_parentheses(value: str, start: int, end: int) -> bool:
    before_index = start - 1
    while before_index >= 0 and value[before_index].isspace():
        before_index -= 1
    if before_index >= 0 and _is_identifier_char(value[before_index]):
        token_end = before_index + 1
        token_start = before_index
        while token_start >= 0 and _is_identifier_char(value[token_start]):
            token_start -= 1
        previous_token = value[token_start + 1:token_end].lower()
        if previous_token not in {"and", "or", "not", "in"}:
            return False
    inner = value[start + 1:end].strip()
    if not inner:
        return False
    if _has_top_level_comma(inner):
        return False
    if _has_top_level_boolean_operator(inner):
        return False
    return True


def _remove_atomic_parentheses(value: str) -> str:
    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(value):
            if value[index] != "(":
                index += 1
                continue
            end = _find_matching_parenthesis(value, index)
            if end is None:
                break
            if _can_remove_parentheses(value, index, end):
                value = value[:index] + value[index + 1:end] + value[end + 1:]
                changed = True
                break
            index += 1
    return value


_NUMERIC_BOUND = r"-?\d+(?:\.\d+)?"
_BOUNDED_EXPRESSION = r"[a-z_][a-z0-9_]*(?:\s*\(\s*[a-z_][a-z0-9_]*\s*\))?"
_NUMERIC_BETWEEN = re.compile(
    rf"(?P<expression>\b{_BOUNDED_EXPRESSION})\s+between\s+"
    rf"(?P<lower>{_NUMERIC_BOUND})\s+and\s+(?P<upper>{_NUMERIC_BOUND})\b"
)


def _normalize_numeric_between(value: str) -> str:
    """Expand bounded numeric BETWEEN expressions to PostgreSQL's canonical form."""
    return _NUMERIC_BETWEEN.sub(
        lambda match: (
            f"({match.group('expression')} >= {match.group('lower')} and "
            f"{match.group('expression')} <= {match.group('upper')})"
        ),
        value,
    )

def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized.startswith("check"):
        normalized = normalized[5:].strip()
    normalized = re.sub(r"\((\d+)\)::(?:text|numeric|bigint|integer|boolean)", r"\1", normalized)
    normalized = re.sub(r"::(?:text|numeric|bigint|integer|boolean)", "", normalized)
    normalized = re.sub(r"([a-z_]+) = any \(array\[(.*?)\]\)", r"\1 in (\2)", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _normalize_numeric_between(normalized)
    normalized = _strip_outer_parentheses(normalized)
    normalized = _remove_atomic_parentheses(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _default_matches(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return actual is None
    return _norm(actual) == expected or (expected == "now()" and _norm(actual) == "now()")


def validate_schema_snapshot(snapshot: dict[str, Any], expectations: dict[str, Any] | None = None) -> None:
    expectations = expectations or FINAL_SCHEMA_EXPECTATIONS
    expected_tables = expectations["tables"]
    tables = set(snapshot.get("tables", set()))
    if tables != expected_tables:
        missing = expected_tables - tables
        extra = tables - expected_tables
        details = []
        if missing:
            details.append(f"missing expected tables: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected public tables: {', '.join(sorted(extra))}")
        raise SchemaCompatibilityError("; ".join(details))
    for table, expected_columns in expectations["columns"].items():
        actual_columns = snapshot.get("columns", {}).get(table, {})
        if set(actual_columns) != set(expected_columns):
            raise SchemaCompatibilityError(f"incompatible column set for {table}")
        for column, expected in expected_columns.items():
            actual = tuple(actual_columns[column])
            if actual[:3] != expected[:3] or not _default_matches(actual[3], expected[3]):
                raise SchemaCompatibilityError(f"incompatible column {table}.{column}")
    for table, columns in expectations["primary_keys"].items():
        if tuple(snapshot.get("primary_keys", {}).get(table, ())) != columns:
            raise SchemaCompatibilityError(f"incompatible primary key for {table}")
    actual_uniques = {(table, tuple(cols)) for table, cols in snapshot.get("unique_constraints", set())}
    expected_uniques = expectations["unique_constraints"]
    if expected_uniques != actual_uniques:
        raise SchemaCompatibilityError(f"incompatible unique constraints: missing={sorted(expected_uniques - actual_uniques)} unexpected={sorted(actual_uniques - expected_uniques)}")
    actual_foreign_keys = {(table, tuple(cols), ref, tuple(ref_cols), action) for table, cols, ref, ref_cols, action in snapshot.get("foreign_keys", set())}
    expected_foreign_keys = expectations["foreign_keys"]
    if expected_foreign_keys != actual_foreign_keys:
        raise SchemaCompatibilityError(f"incompatible foreign keys: missing={sorted(expected_foreign_keys - actual_foreign_keys)} unexpected={sorted(actual_foreign_keys - expected_foreign_keys)}")
    checks = snapshot.get("check_constraints", {})
    actual_check_names = set(checks)
    expected_checks = expectations["check_constraints"]
    expected_check_names = set(expected_checks)
    if actual_check_names != expected_check_names:
        raise SchemaCompatibilityError(f"incompatible check constraint set: missing={sorted(expected_check_names - actual_check_names)} unexpected={sorted(actual_check_names - expected_check_names)}")
    for name, expected in expected_checks.items():
        actual = _norm(checks[name]) or ""
        expected_normalized = _norm(expected) or ""
        if actual != expected_normalized:
            raise SchemaCompatibilityError(f"incompatible check constraint {name}: expected={expected_normalized!r} actual={actual!r}")
    indexes = snapshot.get("indexes", {})
    actual_index_names = set(indexes)
    expected_indexes = expectations["indexes"]
    expected_index_names = set(expected_indexes)
    if actual_index_names != expected_index_names:
        raise SchemaCompatibilityError(f"incompatible explicit index set: missing={sorted(expected_index_names - actual_index_names)} unexpected={sorted(actual_index_names - expected_index_names)}")
    for name, expected in expected_indexes.items():
        actual = indexes[name]
        if (actual[0], bool(actual[1]), tuple(actual[2]), _norm(actual[3])) != (expected[0], expected[1], expected[2], _norm(expected[3])):
            raise SchemaCompatibilityError(f"incompatible index {name}")


def validate_schema_stage(snapshot: dict[str, Any], expectations: dict[str, Any]) -> None:
    """Validate an exact stage or the complete final schema, rejecting partial later DDL."""
    tables = set(snapshot.get("tables", set()))
    later_tables = FINAL_SCHEMA_EXPECTATIONS["tables"] - expectations["tables"]
    present_later = tables & later_tables
    if present_later:
        if present_later != later_tables:
            raise SchemaCompatibilityError("newer schema is an unknown partial state")
        validate_schema_snapshot(snapshot, FINAL_SCHEMA_EXPECTATIONS)
        return
    validate_schema_snapshot(snapshot, expectations)


def validate_one_of_exact_schema_stages(
        snapshot: dict[str, Any], named_expectations: dict[str, dict[str, Any]]) -> str:
    """Return the single exact matching stage; reject partial or ambiguous catalogs."""
    matches = []
    for name, expectations in named_expectations.items():
        try:
            validate_schema_snapshot(snapshot, expectations)
        except SchemaCompatibilityError:
            continue
        matches.append(name)
    if len(matches) != 1:
        detail = "no exact stage matched" if not matches else f"ambiguous stages: {', '.join(matches)}"
        raise SchemaCompatibilityError(detail)
    return matches[0]


def fetch_schema_snapshot(cursor) -> dict[str, Any]:
    cursor.execute("""
        SELECT c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
    """)
    tables = {row[0] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT c.relname, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod),
               CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END,
               a.attidentity,
               pg_catalog.pg_get_expr(d.adbin, d.adrelid)
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    """)
    columns: dict[str, dict[str, tuple[str, str, str, str | None]]] = {}
    for table, column, data_type, nullable, identity, default in cursor.fetchall():
        columns.setdefault(table, {})[column] = (data_type, nullable, identity or "", default)

    cursor.execute("""
        SELECT con.oid, rel.relname, con.contype, con.conname,
               COALESCE(local_cols.columns, ARRAY[]::text[]), ref_rel.relname,
               COALESCE(ref_cols.columns, ARRAY[]::text[]), con.confdeltype,
               CASE
                   WHEN con.contype = 'c' THEN pg_catalog.pg_get_expr(con.conbin, con.conrelid)
                   ELSE pg_catalog.pg_get_constraintdef(con.oid)
               END
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class rel ON rel.oid = con.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = rel.relnamespace
        LEFT JOIN pg_catalog.pg_class ref_rel ON ref_rel.oid = con.confrelid
        LEFT JOIN LATERAL (
            SELECT array_agg(att.attname ORDER BY keys.ord) AS columns
            FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ord)
            JOIN pg_catalog.pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = keys.attnum
        ) local_cols ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(att.attname ORDER BY keys.ord) AS columns
            FROM unnest(con.confkey) WITH ORDINALITY AS keys(attnum, ord)
            JOIN pg_catalog.pg_attribute att ON att.attrelid = con.confrelid AND att.attnum = keys.attnum
        ) ref_cols ON true
        WHERE n.nspname = 'public' AND rel.relkind = 'r'
        ORDER BY rel.relname, con.oid
    """)
    primary: dict[str, tuple[str, ...]] = {}
    uniques: set[tuple[str, tuple[str, ...]]] = set()
    foreign_keys: set[tuple[str, tuple[str, ...], str, tuple[str, ...], str]] = set()
    checks: dict[str, str] = {}
    for _oid, table, contype, name, local_cols, ref_table, ref_cols, delete_action, definition in cursor.fetchall():
        local_tuple = tuple(local_cols or ())
        if contype == "p":
            primary[table] = local_tuple
        elif contype == "u":
            uniques.add((table, local_tuple))
        elif contype == "f":
            foreign_keys.add((table, local_tuple, ref_table, tuple(ref_cols or ()), delete_action))
        elif contype == "c":
            checks[name] = _norm(definition) or ""

    cursor.execute("""
        SELECT idx.relname, tbl.relname, i.indisunique,
               array_agg(att.attname ORDER BY keys.ord),
               array_agg(CASE WHEN (i.indoption[keys.ord - 1] & 1) = 1 THEN 'DESC' ELSE 'ASC' END ORDER BY keys.ord),
               pg_catalog.pg_get_expr(i.indpred, i.indrelid)
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_catalog.pg_class tbl ON tbl.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = tbl.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ord) ON keys.attnum <> 0
        JOIN pg_catalog.pg_attribute att ON att.attrelid = tbl.oid AND att.attnum = keys.attnum
        WHERE n.nspname = 'public' AND NOT i.indisprimary AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_constraint con WHERE con.conindid = i.indexrelid AND con.contype IN ('u', 'p')
        )
        GROUP BY idx.relname, tbl.relname, i.indisunique, i.indpred, i.indrelid
        ORDER BY idx.relname
    """)
    indexes = {}
    for name, table, unique, cols, directions, predicate in cursor.fetchall():
        indexes[name] = (table, bool(unique), tuple(zip(cols, directions)), predicate)
    return {"tables": tables, "columns": columns, "primary_keys": primary, "unique_constraints": uniques, "foreign_keys": foreign_keys, "check_constraints": checks, "indexes": indexes}


def initialize_or_validate(database_url: str, schema_path: Path = SCHEMA, connect=None) -> None:
    if not database_url:
        raise ValueError("DATABASE_URL is required; value is intentionally not printed")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    schema_sql = schema_path.read_text()
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.relname FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
            """)
            existing = {row[0] for row in cursor.fetchall()}
            if not existing:
                cursor.execute(schema_sql)
                validate_schema_snapshot(fetch_schema_snapshot(cursor))
            else:
                snapshot = fetch_schema_snapshot(cursor)
                if existing == PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"]:
                    validate_schema_snapshot(snapshot, PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS)
                    cursor.execute(migration_body_for_outer_transaction(PARTICIPANT_MIGRATION.read_text()))
                    snapshot = fetch_schema_snapshot(cursor)
                    validate_schema_snapshot(snapshot, PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS)
                    existing = snapshot["tables"]
                if existing == PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS["tables"]:
                    validate_schema_snapshot(snapshot, PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS)
                    cursor.execute(migration_body_for_outer_transaction(EXECUTION_RESULT_MIGRATION.read_text()))
                    snapshot = fetch_schema_snapshot(cursor)
                    existing = snapshot["tables"]
                if existing == PRE_REALM_CATALOG_EXPECTATIONS["tables"]:
                    validate_schema_snapshot(snapshot, PRE_REALM_CATALOG_EXPECTATIONS)
                    cursor.execute(migration_body_for_outer_transaction(REALM_CATALOG_MIGRATION.read_text()))
                    snapshot = fetch_schema_snapshot(cursor)
                    existing = snapshot["tables"]
                if existing == PRE_REALM_CALL_INDEX_EXPECTATIONS["tables"]:
                    validate_schema_snapshot(snapshot, PRE_REALM_CALL_INDEX_EXPECTATIONS)
                    cursor.execute(migration_body_for_outer_transaction(REALM_CALL_INDEX_MIGRATION.read_text()))
                    snapshot = fetch_schema_snapshot(cursor)
                    existing = snapshot["tables"]
                if existing == PRE_REALM_METADATA_EXPECTATIONS["tables"]:
                    validate_schema_snapshot(snapshot, PRE_REALM_METADATA_EXPECTATIONS)
                    cursor.execute(migration_body_for_outer_transaction(REALM_METADATA_MIGRATION.read_text()))
                    snapshot = fetch_schema_snapshot(cursor)
                    existing = snapshot["tables"]
                if existing == PRE_GOVERNANCE_SCHEMA_EXPECTATIONS["tables"]:
                    try:
                        validate_schema_snapshot(snapshot, PRE_GOVERNANCE_SCHEMA_EXPECTATIONS)
                    except SchemaCompatibilityError:
                        pass
                    else:
                        raise SchemaCompatibilityError(
                            "Governance schema is missing; run:\n"
                            "python scripts/migrate_governance_schema.py"
                        )
                if existing == PRE_NETWORK_DISTRIBUTION_EXPECTATIONS["tables"]:
                    try:
                        validate_schema_snapshot(snapshot, PRE_NETWORK_DISTRIBUTION_EXPECTATIONS)
                    except SchemaCompatibilityError:
                        pass
                    else:
                        raise SchemaCompatibilityError(
                            "Network-distribution schema is missing; run:\n"
                            "python scripts/migrate_network_distribution_schema.py"
                        )
                validate_schema_snapshot(snapshot)
            validate_participant_privileges(cursor)
        connection.commit()


def validate_table_privileges(cursor) -> None:
    """Require late transaction-table grants when configured roles exist."""
    for role, tables in EXPECTED_TABLE_PRIVILEGES.items():
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (role,))
        if not cursor.fetchone()[0]:
            continue
        for table, required in tables.items():
            privileges = {"SELECT", "INSERT", "UPDATE", "DELETE"}
            actual = set()
            for privilege in privileges:
                cursor.execute(
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (role, f"public.{table}", privilege),
                )
                if cursor.fetchone()[0]:
                    actual.add(privilege)
            if role == "utsa_gno_api" and actual != required:
                raise SchemaCompatibilityError(f"API role has incompatible privileges for {table}")
            if role == "utsa_gno_indexer" and not required <= actual:
                raise SchemaCompatibilityError(f"Indexer role lacks privileges for {table}")


def validate_participant_privileges(cursor) -> None:
    """Compatibility entry point for generalized late-table validation."""
    validate_table_privileges(cursor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default=str(SCHEMA), help="Schema SQL file to apply to an empty database.")
    return parser


def _sanitize_message(message: str, database_url: str) -> str:
    sanitized = message.replace(database_url, "[redacted DATABASE_URL]") if database_url else message
    return re.sub(r"(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1[redacted]@", sanitized)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        initialize_or_validate(database_url, Path(args.schema))
    except Exception as exc:
        print(f"Schema initialization failed: {exc.__class__.__name__}: {_sanitize_message(str(exc), database_url)}", file=sys.stderr)
        return 1
    print("Schema initialization/validation succeeded")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
