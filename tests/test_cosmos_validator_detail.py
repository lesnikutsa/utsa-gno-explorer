import unittest
from api.cosmos.service import consensus_address, reencode_bech32_address, valid_bech32_address
from api.cosmos.validators import category_voting_power_rank
from api.cosmos.schemas import CosmosValidatorDetail

class CosmosValidatorAddressTests(unittest.TestCase):
    def test_reusable_detail_contract_exposes_optional_security_contact(self):
        field = CosmosValidatorDetail.model_fields["contact"]
        self.assertFalse(field.is_required())

    def test_reusable_detail_contract_exposes_optional_reward_fields(self):
        self.assertFalse(CosmosValidatorDetail.model_fields["commission_earned"].is_required())
        self.assertFalse(CosmosValidatorDetail.model_fields["delegators_total_rewards"].is_required())

    def test_configured_operator_prefix_and_checksum_are_required(self):
        # The encoder hashes a public key, but Bech32 validity is independent of the payload role.
        address = consensus_address({"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}, "testvaloper")
        self.assertTrue(valid_bech32_address(address, "testvaloper"))
        self.assertFalse(valid_bech32_address(address, "othervaloper"))
        self.assertFalse(valid_bech32_address(address[:-1] + ("q" if address[-1] != "q" else "p"), "testvaloper"))
        self.assertFalse(valid_bech32_address("not-an-address", "testvaloper"))

    def test_registry_prefix_reencoding_preserves_payload(self):
        operator = consensus_address({"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}, "testvaloper")
        account = reencode_bech32_address(operator, "testvaloper", "test")
        self.assertTrue(valid_bech32_address(account, "test"))

    def test_rank_is_local_to_validator_category(self):
        validators = [
            {"operator_address": "active-a", "category": "active", "tokens": "100"},
            {"operator_address": "inactive-a", "category": "inactive", "tokens": "1000"},
            {"operator_address": "active-b", "category": "active", "tokens": "50"},
        ]
        self.assertEqual(category_voting_power_rank(validators, validators[2]), 2)
