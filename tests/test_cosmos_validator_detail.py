import unittest
from api.cosmos.service import consensus_address, valid_bech32_address

class CosmosValidatorAddressTests(unittest.TestCase):
    def test_configured_operator_prefix_and_checksum_are_required(self):
        # The encoder hashes a public key, but Bech32 validity is independent of the payload role.
        address = consensus_address({"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}, "testvaloper")
        self.assertTrue(valid_bech32_address(address, "testvaloper"))
        self.assertFalse(valid_bech32_address(address, "othervaloper"))
        self.assertFalse(valid_bech32_address(address[:-1] + ("q" if address[-1] != "q" else "p"), "testvaloper"))
        self.assertFalse(valid_bech32_address("not-an-address", "testvaloper"))
