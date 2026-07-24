import copy
import pytest
from scripts import init_database

def snapshot(expectations):
 return {'tables':set(expectations['tables']),'columns':copy.deepcopy(expectations['columns']),'primary_keys':copy.deepcopy(expectations['primary_keys']),'unique_constraints':set(expectations['unique_constraints']),'foreign_keys':set(expectations['foreign_keys']),'check_constraints':copy.deepcopy(expectations['check_constraints']),'indexes':copy.deepcopy(expectations['indexes'])}

def test_pre_network_and_final_are_exact_valid_stages():
 init_database.validate_schema_stage(snapshot(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS),init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS)
 init_database.validate_schema_stage(snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS),init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS)

def test_partial_newer_stage_is_rejected():
 value=snapshot(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS); value['tables'].add('network_distribution_geo_cache')
 with pytest.raises(init_database.SchemaCompatibilityError,match='partial'): init_database.validate_schema_stage(value,init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS)

def test_final_validation_does_not_accept_pre_network_stage():
 with pytest.raises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS))

def test_five_historical_stages_are_exact_and_distinct():
 stages={
  'base':init_database.BASE_LEGACY_EXPECTATIONS,
  'valopers-only':init_database.VALOPERS_ONLY_EXPECTATIONS,
  'transaction-hash-only':init_database.TRANSACTION_HASH_ONLY_EXPECTATIONS,
  'pre-network':init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
  'final':init_database.FINAL_SCHEMA_EXPECTATIONS,
 }
 for name,expectations in stages.items():
  assert init_database.validate_one_of_exact_schema_stages(snapshot(expectations),stages)==name

def test_unknown_partial_hash_stage_is_rejected():
 stages={'base':init_database.BASE_LEGACY_EXPECTATIONS,'hash':init_database.TRANSACTION_HASH_ONLY_EXPECTATIONS}
 value=snapshot(init_database.BASE_LEGACY_EXPECTATIONS)
 value['columns']['transactions']['tx_hash_hex']=init_database.EXPECTED_COLUMNS['transactions']['tx_hash_hex']
 with pytest.raises(init_database.SchemaCompatibilityError): init_database.validate_one_of_exact_schema_stages(value,stages)
