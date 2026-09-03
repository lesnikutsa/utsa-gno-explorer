import unittest

from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.validator_activity import EVENT_KEYS, merge_activity, normalize_transaction


VAL = "atonevaloper1validator"
ACCOUNT = "atone1validator"


def transaction(messages, height="42", txhash="A" * 64, code=0, logs=None):
    return ({"body": {"messages": messages}}, {"height": height, "txhash": txhash,
            "timestamp": "2026-01-02T03:04:05Z", "code": code, "logs": logs or []})


class ValidatorActivityTests(unittest.TestCase):
    def normalize(self, message, **kwargs):
        tx, response = transaction([message], **kwargs)
        return normalize_transaction(tx, response, VAL, ACCOUNT)

    def test_staking_actions_and_exact_amounts(self):
        cases = [
            ({"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL, "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "900719925474099312345"}}, "delegate", "positive"),
            ({"@type": "/cosmos.staking.v1beta1.MsgUndelegate", "validator_address": VAL, "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "2"}}, "undelegate", "negative"),
            ({"@type": "/cosmos.staking.v1beta1.MsgBeginRedelegate", "validator_src_address": VAL, "validator_dst_address": "other", "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "3"}}, "redelegate_out", "negative"),
            ({"@type": "/cosmos.staking.v1beta1.MsgBeginRedelegate", "validator_src_address": "other", "validator_dst_address": VAL, "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "4"}}, "redelegate_in", "positive"),
        ]
        for message, action, direction in cases:
            with self.subTest(action=action):
                item = self.normalize(message)[0]
                self.assertEqual((item["action"], item["direction"]), (action, direction))
        self.assertEqual(self.normalize(cases[0][0])[0]["amounts"][0]["amount"], "900719925474099312345")

    def test_withdrawals_amounts_are_log_scoped_and_multi_denom(self):
        logs = [{"msg_index": 0, "events": [{"type": "withdraw_rewards", "attributes": [{"key": "amount", "value": "8uatone,4uphoton"}]}]}]
        reward = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", "validator_address": VAL, "delegator_address": "atone1d"}
        commission = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission", "validator_address": VAL}
        self.assertEqual(len(self.normalize(reward, logs=logs)[0]["amounts"]), 2)
        self.assertEqual(self.normalize(commission)[0]["amounts"], [])

    def test_edit_unjail_failed_and_multi_message(self):
        edit = {"@type": "/cosmos.staking.v1beta1.MsgEditValidator", "validator_address": VAL, "commission_rate": "0.05"}
        unjail = {"@type": "/cosmos.slashing.v1beta1.MsgUnjail", "validator_addr": VAL}
        tx, response = transaction([edit, unjail])
        items = normalize_transaction(tx, response, VAL, ACCOUNT)
        self.assertEqual([item["message_index"] for item in items], [0, 1])
        self.assertEqual(items[0]["detail"], "Commission → 5.00%")
        self.assertEqual(normalize_transaction(*transaction([edit], code=7), VAL, ACCOUNT), [])

    def test_merge_deduplicates_and_orders_deterministically(self):
        message = {"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL, "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1"}}
        a = transaction([message], height="2", txhash="B" * 64)
        b = transaction([message], height="3", txhash="C" * 64)
        payload = lambda pair: {"txs": [pair[0]], "tx_responses": [pair[1]]}
        result = merge_activity([payload(a), payload(b), payload(b)], VAL, ACCOUNT)
        self.assertEqual([item["height"] for item in result], [3, 2])
        self.assertEqual(len(result), 2)

    def test_hard_cap_malformed_and_bounded_fanout(self):
        message = {"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL, "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1"}}
        payloads = []
        for height in range(1, 61):
            pair = transaction([message], height=str(height), txhash=f"{height:064X}")
            payloads.append({"txs": [pair[0]], "tx_responses": [pair[1]]})
        self.assertEqual(len(merge_activity(payloads, VAL, ACCOUNT)), 50)
        self.assertEqual(len(EVENT_KEYS), 6)
        with self.assertRaises(MalformedUpstreamResponse):
            merge_activity([{"txs": [], "tx_responses": [{}]}], VAL, ACCOUNT)


if __name__ == "__main__":
    unittest.main()
