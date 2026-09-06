import unittest

from api.cosmos.consensus import _aggregate_hashes, _height_round_step, _vote


class CosmosConsensusParsingTests(unittest.TestCase):
    def test_height_round_step_accepts_comet_compound_field(self):
        self.assertEqual(_height_round_step({"height/round/step": "10239328/2/6"}), (10239328, 2, 6))

    def test_vote_distinguishes_missing_nil_and_block_hash(self):
        self.assertEqual(_vote("nil-Vote", "Prevote"), ("missing", None))
        self.assertEqual(_vote("Vote{0:ABC 10/00/SIGNED_MSG_TYPE_PREVOTE(Prevote) nil @ 2026-01-01T00:00:00Z}", "Prevote"), ("nil", None))
        state, vote_hash = _vote("Vote{0:ABC 10/00/SIGNED_MSG_TYPE_PREVOTE(Prevote) AABBCCDDEEFF0011 @ 2026-01-01T00:00:00Z}", "Prevote")
        self.assertEqual(state, "signed")
        self.assertEqual(vote_hash, "AABBCCDDEEFF0011")

    def test_hash_aggregation_uses_voting_power_and_flags_competing_hashes(self):
        validators = [
            {"voting_power": 70, "prevote": "signed", "prevote_hash": "AAAAAA"},
            {"voting_power": 20, "prevote": "signed", "prevote_hash": "BBBBBB"},
            {"voting_power": 10, "prevote": "missing", "prevote_hash": None},
        ]
        groups, participation, missing, competing = _aggregate_hashes(validators, "prevote", 100)
        self.assertEqual([row["hash"] for row in groups], ["AAAAAA", "BBBBBB"])
        self.assertEqual(participation, 90.0)
        self.assertEqual(missing, 10.0)
        self.assertTrue(competing)


if __name__ == "__main__":
    unittest.main()
