import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.cosmos.account_activity import (
    event_queries,
    load_account_activity,
    merge_account_activity,
    normalize_transaction,
)
from api.cosmos.errors import AllEndpointsUnavailable, MalformedUpstreamResponse


ACCOUNT = "atone1account"
VAL_A = "atonevaloper1validatora"
VAL_B = "atonevaloper1validatorb"


def transaction(messages, *, height="42", txhash="A" * 64, code=0, logs=None, events=None):
    tx = {"body": {"messages": messages}}
    response = {
        "height": height,
        "txhash": txhash,
        "timestamp": "2026-09-05T12:34:56Z",
        "code": code,
        "logs": logs or [],
        "events": events or [],
    }
    return tx, response


def payload(pair):
    return {"txs": [pair[0]], "tx_responses": [pair[1]]}


class AccountActivityNormalizationTests(unittest.TestCase):
    def test_send_receive_and_exact_amounts(self):
        sent = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": ACCOUNT,
                "to_address": "atone1recipient",
                "amount": [{"denom": "uatone", "amount": "900719925474099312345"}]}
        received = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": "atone1sender",
                    "to_address": ACCOUNT, "amount": [{"denom": "uatone", "amount": "7"}]}
        sent_item = normalize_transaction(*transaction([sent]), ACCOUNT, "message.sender")
        received_item = normalize_transaction(*transaction([received]), ACCOUNT, "transfer.recipient")
        self.assertEqual((sent_item["action"], sent_item["direction"]), ("sent", "negative"))
        self.assertEqual(sent_item["amounts"][0]["amount"], "900719925474099312345")
        self.assertEqual((received_item["action"], received_item["direction"]), ("received", "positive"))
        self.assertEqual(received_item["detail"], "atone1sender")

    def test_staking_reward_governance_and_ibc_actions(self):
        cases = [
            ({"@type": "/cosmos.staking.v1beta1.MsgDelegate", "delegator_address": ACCOUNT,
              "validator_address": VAL_A, "amount": {"denom": "uatone", "amount": "10"}}, "delegate"),
            ({"@type": "/cosmos.staking.v1beta1.MsgUndelegate", "delegator_address": ACCOUNT,
              "validator_address": VAL_A, "amount": {"denom": "uatone", "amount": "11"}}, "undelegate"),
            ({"@type": "/cosmos.staking.v1beta1.MsgBeginRedelegate", "delegator_address": ACCOUNT,
              "validator_src_address": VAL_A, "validator_dst_address": VAL_B,
              "amount": {"denom": "uatone", "amount": "12"}}, "redelegate"),
            ({"@type": "/cosmos.gov.v1.MsgVote", "voter": ACCOUNT, "proposal_id": "9", "option": "VOTE_OPTION_YES"}, "vote"),
            ({"@type": "/ibc.applications.transfer.v1.MsgTransfer", "sender": ACCOUNT,
              "receiver": "cosmos1remote", "source_channel": "channel-7",
              "token": {"denom": "uatone", "amount": "13"}}, "ibc_transfer"),
        ]
        for message, action in cases:
            with self.subTest(action=action):
                item = normalize_transaction(*transaction([message]), ACCOUNT, "message.sender")
                self.assertEqual(item["action"], action)

        logs = [{"msg_index": 0, "events": [{"type": "withdraw_rewards", "attributes": [
            {"key": "validator", "value": VAL_A},
            {"key": "amount", "value": "15uatone,2uphoton"},
        ]}]}]
        reward = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward",
                  "delegator_address": ACCOUNT, "validator_address": VAL_A}
        item = normalize_transaction(*transaction([reward], logs=logs), ACCOUNT, "message.sender")
        self.assertEqual(item["action"], "withdraw_reward")
        self.assertEqual(len(item["amounts"]), 2)

    def test_inbound_ibc_uses_recv_packet_not_relayer_update_client(self):
        update_client = {"@type": "/ibc.core.client.v1.MsgUpdateClient", "signer": "atone1relayer"}
        recv_packet = {"@type": "/ibc.core.channel.v1.MsgRecvPacket", "packet": {
            "source_channel": "channel-9", "destination_channel": "channel-2",
        }, "signer": "atone1relayer"}
        events = [{"type": "transfer", "attributes": [
            {"key": "recipient", "value": ACCOUNT},
            {"key": "sender", "value": "osmo1remote"},
            {"key": "amount", "value": "24000000uatone"},
        ]}]
        item = normalize_transaction(
            *transaction([update_client, recv_packet], events=events), ACCOUNT, "transfer.recipient")
        self.assertEqual((item["action"], item["direction"]), ("ibc_received", "positive"))
        self.assertEqual(item["message_index"], 1)
        self.assertEqual(item["type_url"], "/ibc.core.channel.v1.MsgRecvPacket")
        self.assertEqual(item["detail"], "channel-9 → channel-2")
        self.assertEqual(item["amounts"], [{"denom": "uatone", "amount": "24000000"}])

    def test_failed_transaction_never_claims_value_movement(self):
        message = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": ACCOUNT,
                   "to_address": "atone1recipient", "amount": [{"denom": "uatone", "amount": "5"}]}
        item = normalize_transaction(*transaction([message], code=7), ACCOUNT, "message.sender")
        self.assertFalse(item["success"])
        self.assertEqual(item["direction"], "neutral")
        self.assertEqual(item["amounts"], [])

    def test_received_event_fallback_and_transaction_fallback(self):
        logs = [{"msg_index": 0, "events": [{"type": "transfer", "attributes": [
            {"key": "recipient", "value": ACCOUNT}, {"key": "amount", "value": "22uatone"},
        ]}]}]
        unknown = {"@type": "/custom.module.v1.MsgDoThing", "value": "x"}
        received = normalize_transaction(*transaction([unknown], logs=logs), ACCOUNT, "transfer.recipient")
        authored = normalize_transaction(*transaction([unknown]), ACCOUNT, "message.sender")
        self.assertEqual((received["action"], received["amounts"][0]["amount"]), ("received", "22"))
        self.assertEqual(authored["action"], "transaction")
        self.assertEqual(authored["type_url"], "/custom.module.v1.MsgDoThing")

    def test_merge_deduplicates_by_transaction_and_orders(self):
        message = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": ACCOUNT,
                   "to_address": ACCOUNT, "amount": [{"denom": "uatone", "amount": "1"}]}
        older = transaction([message], height="2", txhash="B" * 64)
        newer = transaction([message], height="3", txhash="C" * 64)
        result = merge_account_activity([
            ("message.sender", payload(older)),
            ("message.sender", payload(newer)),
            ("transfer.recipient", payload(newer)),
        ], ACCOUNT)
        self.assertEqual([item["height"] for item in result], [3, 2])
        self.assertEqual(len(result), 2)

    def test_strict_search_shape(self):
        with self.assertRaises(MalformedUpstreamResponse):
            merge_account_activity([("message.sender", {"txs": [{}], "tx_responses": []})], ACCOUNT)
        self.assertEqual(event_queries(ACCOUNT), (("message.sender", ACCOUNT), ("transfer.recipient", ACCOUNT)))


class AccountActivityServiceTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        return SimpleNamespace(
            definition=SimpleNamespace(account_prefix="atone"),
            _validator_event_search=AsyncMock(),
        )

    async def test_available_partial_unavailable_and_pagination(self):
        service = self.service()
        empty = {"txs": [], "tx_responses": []}
        with patch("api.cosmos.service.valid_bech32_address", return_value=True):
            service._validator_event_search.return_value = empty
            first = await load_account_activity(service, ACCOUNT)
            self.assertEqual(first["state"], "available")
            self.assertEqual(service._validator_event_search.await_count, 2)
            self.assertTrue(all(call.args[1] == 11 for call in service._validator_event_search.await_args_list))

            service._validator_event_search.reset_mock()
            service._validator_event_search.side_effect = [empty, AllEndpointsUnavailable("down")]
            partial = await load_account_activity(service, ACCOUNT)
            self.assertEqual(partial["state"], "partial")

            service._validator_event_search.reset_mock()
            service._validator_event_search.side_effect = AllEndpointsUnavailable("disabled")
            unavailable = await load_account_activity(service, ACCOUNT)
            self.assertEqual(unavailable["state"], "indexing_unavailable")

            message = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": ACCOUNT,
                       "to_address": "atone1recipient", "amount": [{"denom": "uatone", "amount": "1"}]}
            pairs = [transaction([message], height=str(height), txhash=f"{height:064X}")
                     for height in range(50, 0, -1)]

            async def bounded(_expression, requested_limit):
                selected = pairs[:requested_limit]
                return {"txs": [pair[0] for pair in selected],
                        "tx_responses": [pair[1] for pair in selected]}

            service._validator_event_search = AsyncMock(side_effect=bounded)
            first = await load_account_activity(service, ACCOUNT, page=1)
            second = await load_account_activity(service, ACCOUNT, page=2)
            fifth = await load_account_activity(service, ACCOUNT, page=5)
            self.assertEqual((first["items"][0]["height"], second["items"][0]["height"], fifth["items"][0]["height"]),
                             (50, 40, 10))
            self.assertTrue(first["has_more"])
            self.assertFalse(fifth["has_more"])

    async def test_invalid_request_is_rejected_before_search(self):
        service = self.service()
        with patch("api.cosmos.service.valid_bech32_address", return_value=False):
            with self.assertRaises(ValueError):
                await load_account_activity(service, ACCOUNT)
        with patch("api.cosmos.service.valid_bech32_address", return_value=True):
            for limit, page in ((0, 1), (11, 1), (10, 0), (10, 6)):
                with self.assertRaises(ValueError):
                    await load_account_activity(service, ACCOUNT, limit, page)


if __name__ == "__main__":
    unittest.main()
