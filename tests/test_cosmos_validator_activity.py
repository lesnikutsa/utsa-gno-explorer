import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from api.cosmos import RequestCache
from api.cosmos.errors import AllEndpointsUnavailable, InvalidValidatorAddress, MalformedUpstreamResponse
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService
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
        logs = [{"msg_index": 0, "events": [{"type": "withdraw_rewards", "attributes": [{"key": "validator", "value": VAL}, {"key": "amount", "value": "10568698uatone,22202uphoton"}]}]}]
        reward = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", "validator_address": VAL, "delegator_address": "atone1d"}
        commission = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission", "validator_address": VAL}
        self.assertEqual(len(self.normalize(reward, logs=logs)[0]["amounts"]), 2)
        mismatch = [{"msg_index": 0, "events": [{"type": "withdraw_rewards", "attributes": [{"key": "validator", "value": "other"}, {"key": "amount", "value": "8uatone"}]}]}]
        self.assertEqual(self.normalize(reward, logs=mismatch)[0]["amounts"], [])
        commission_logs = [{"msg_index": 0, "events": [{"type": "withdraw_commission", "attributes": [{"key": "amount", "value": "8uatone,4uphoton"}]}]}]
        self.assertEqual(len(self.normalize(commission, logs=commission_logs)[0]["amounts"]), 2)
        self.assertEqual(self.normalize(commission)[0]["amounts"], [])
        ambiguous = [{"msg_index": 0, "events": [commission_logs[0]["events"][0], commission_logs[0]["events"][0]]}]
        self.assertEqual(self.normalize(commission, logs=ambiguous)[0]["amounts"], [])

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

    def test_strict_transaction_identity_and_irrelevant_sender_message(self):
        transfer = {"@type": "/ibc.applications.transfer.v1.MsgTransfer", "sender": ACCOUNT}
        self.assertEqual(self.normalize(transfer), [])
        with self.assertRaises(MalformedUpstreamResponse):
            self.normalize({"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL}, txhash="garbage")
        valid = {"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL,
                 "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1"}}
        item = self.normalize(valid, txhash="a" * 64)[0]
        self.assertEqual(item["tx_hash"], "A" * 64)

    def test_exact_types_and_relevant_message_fields_are_strict(self):
        valid = {"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL,
                 "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1"}}
        self.assertEqual(self.normalize({**valid, "@type": "/fake.MsgDelegate"}), [])
        self.assertEqual(self.normalize(valid)[0]["action"], "delegate")
        malformed = [
            {"@type": valid["@type"], "validator_address": VAL, "amount": valid["amount"]},
            {"@type": valid["@type"], "validator_address": VAL, "delegator_address": "atone1d"},
            {"@type": "/cosmos.staking.v1beta1.MsgUndelegate", "validator_address": VAL,
             "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1.5"}},
            {"@type": "/cosmos.staking.v1beta1.MsgBeginRedelegate",
             "validator_src_address": VAL, "delegator_address": "atone1d",
             "amount": {"denom": "uatone", "amount": "1"}},
            {"@type": "/cosmos.staking.v1beta1.MsgEditValidator",
             "validator_address": VAL, "commission_rate": "1.01"},
        ]
        for message in malformed:
            with self.subTest(message=message["@type"]), self.assertRaises(MalformedUpstreamResponse):
                self.normalize(message)

    def test_valid_reward_message_without_event_keeps_empty_amounts(self):
        reward = {"@type": "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward",
                  "validator_address": VAL, "delegator_address": "atone1d"}
        self.assertEqual(self.normalize(reward)[0]["amounts"], [])


class ValidatorActivityServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient()
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_modern_shape_and_empty_result_do_not_fallback(self):
        self.service.adapter._cached_candidates = AsyncMock(return_value=(SimpleNamespace(endpoint="https://rest.test"),))
        empty = {"txs": [], "tx_responses": []}
        self.service.transport.get_object = AsyncMock(return_value=empty)
        self.assertEqual(await self.service._validator_event_search("delegate.validator='v'", 11), empty)
        self.service.transport.get_object.assert_awaited_once()
        path = self.service.transport.get_object.await_args.args[1]
        self.assertIn("?query=", path)
        self.assertIn("&order_by=ORDER_BY_DESC&page=1&limit=11", path)
        self.assertNotIn("pagination.limit", path)

    async def test_explicit_modern_incompatibility_uses_legacy_once(self):
        self.service.adapter._cached_candidates = AsyncMock(return_value=(SimpleNamespace(endpoint="https://rest.test"),))
        self.service.transport.get_object = AsyncMock(side_effect=[
            {"code": 3, "message": "unknown field query in GetTxsEventRequest"},
            {"txs": [], "tx_responses": []},
        ])
        await self.service._validator_event_search("delegate.validator='v'", 10)
        self.assertEqual(self.service.transport.get_object.await_count, 2)
        self.assertIn("?events=", self.service.transport.get_object.await_args_list[1].args[1])
        self.assertIn("&page=1&limit=10", self.service.transport.get_object.await_args_list[1].args[1])

    async def test_indexing_error_does_not_use_legacy(self):
        self.service.adapter._cached_candidates = AsyncMock(return_value=(SimpleNamespace(endpoint="https://rest.test"),))
        self.service.transport.get_object = AsyncMock(return_value={"code": 13, "message": "transaction indexing is disabled"})
        with self.assertRaises(AllEndpointsUnavailable):
            await self.service._validator_event_search("delegate.validator='v'", 10)
        self.service.transport.get_object.assert_awaited_once()

    async def test_event_search_rejects_oversize_mismatched_and_bad_pagination(self):
        self.service.adapter._cached_candidates = AsyncMock(return_value=(SimpleNamespace(endpoint="https://rest.test"),))
        for payload in (
                {"txs": [{}] * 12, "tx_responses": [{}] * 12},
                {"txs": [{}], "tx_responses": []},
                {"txs": [], "tx_responses": [], "pagination": []}):
            self.service.transport.get_object = AsyncMock(return_value=payload)
            with self.assertRaises(AllEndpointsUnavailable):
                await self.service._validator_event_search(f"delegate.validator='{id(payload)}'", 11)
            self.service.transport.get_object.assert_awaited_once()
        accepted = {"txs": [{}] * 11, "tx_responses": [{}] * 11, "pagination": {"total": "11"}}
        self.service.transport.get_object = AsyncMock(return_value=accepted)
        self.assertEqual(await self.service._validator_event_search("delegate.validator='exact'", 11), accepted)

    async def test_states_fanout_bounds_and_pagination(self):
        empty = {"txs": [], "tx_responses": []}
        with patch("api.cosmos.service.valid_bech32_address", return_value=True), \
                patch("api.cosmos.service.reencode_bech32_address", return_value=ACCOUNT):
            self.service._validator_event_search = AsyncMock(return_value=empty)
            available = await self.service.validator_activity(VAL)
            self.assertEqual(available["state"], "available")
            self.assertEqual(self.service._validator_event_search.await_count, 6)
            self.assertTrue(all(call.args[1] == 11 for call in self.service._validator_event_search.await_args_list))

            self.service._validator_event_search = AsyncMock(side_effect=[empty] * 5 + [AllEndpointsUnavailable("down")])
            self.assertEqual((await self.service.validator_activity(VAL))["state"], "partial")
            self.service._validator_event_search = AsyncMock(side_effect=AllEndpointsUnavailable("index disabled"))
            self.assertEqual((await self.service.validator_activity(VAL))["state"], "indexing_unavailable")

            self.service._validator_event_search = AsyncMock(return_value=empty)
            await self.service.validator_activity(VAL, limit=10, page=5)
            self.assertTrue(all(call.args[1] == 50 for call in self.service._validator_event_search.await_args_list))

            message = {"@type": "/cosmos.staking.v1beta1.MsgDelegate", "validator_address": VAL,
                       "delegator_address": "atone1d", "amount": {"denom": "uatone", "amount": "1"}}
            pairs = [transaction([message], height=str(height), txhash=f"{height:064X}")
                     for height in range(50, 0, -1)]
            async def bounded_payload(_expression, requested_limit):
                selected = pairs[:requested_limit]
                return {"txs": [pair[0] for pair in selected],
                        "tx_responses": [pair[1] for pair in selected]}
            self.service._validator_event_search = AsyncMock(side_effect=bounded_payload)
            first = await self.service.validator_activity(VAL, page=1)
            second = await self.service.validator_activity(VAL, page=2)
            fifth = await self.service.validator_activity(VAL, page=5)
            self.assertEqual((first["items"][0]["height"], second["items"][0]["height"],
                              fifth["items"][0]["height"]), (50, 40, 10))
            self.assertTrue(first["has_more"])
            self.assertFalse(fifth["has_more"])

    async def test_invalid_pagination_and_validator(self):
        for limit, page in ((0, 1), (11, 1), (10, 0), (10, 6)):
            with self.assertRaises(ValueError):
                with patch("api.cosmos.service.valid_bech32_address", return_value=True):
                    await self.service.validator_activity(VAL, limit, page)
        with self.assertRaises(InvalidValidatorAddress):
            await self.service.validator_activity("invalid")


if __name__ == "__main__":
    unittest.main()
