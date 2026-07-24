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
