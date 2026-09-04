import base64
import unittest

from api.cosmos.schemas import TransactionDetailResponse
from api.cosmos.transaction_detail import normalize_transaction_detail

TIME = "2026-09-04T16:22:16Z"


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def coin(amount="1234567", denom="uatone"):
    return field(1, denom) + field(2, amount)


def tx(messages):
    body = b"".join(field(1, field(1, type_url) + field(2, payload)) for type_url, payload in messages)
    fee = field(1, coin("5000", "uphoton")) + field(2, 200000)
    auth = field(2, fee)
    return field(1, body) + field(2, auth) + field(3, b"signature")


def event(event_type, attributes, msg_index=None):
    values = [{"key": key, "value": value, "index": True} for key, value in attributes.items()]
    if msg_index is not None:
        values.append({"key": "msg_index", "value": str(msg_index), "index": True})
    return {"type": event_type, "attributes": values}


def normalize(messages, events=None, code=0):
    raw = tx(messages)
    block = {"result": {"block": {"header": {"chain_id": "atomone-1", "height": "10", "time": TIME},
                                      "data": {"txs": [base64.b64encode(raw).decode()]}}}}
    tx_result = {"code": code, "gas_used": "100", "gas_wanted": "200"}
    if events is not None:
        tx_result["events"] = events
    results = {"result": {"height": "10", "txs_results": [tx_result]}}
    detail = normalize_transaction_detail(block, results, expected_chain_id="atomone-1", requested_height=10, tx_index=0)
    TransactionDetailResponse.model_validate(detail)
    return detail


class CosmosTransactionMessageDetailsTest(unittest.TestCase):
    def test_existing_send_decoder_stays_human_readable(self):
        payload = field(1, "atone1from") + field(2, "atone1to") + field(3, coin())
        message = normalize([("/cosmos.bank.v1beta1.MsgSend", payload)])["messages"][0]
        self.assertEqual(message["action"], "Send")
        self.assertEqual([item["label"] for item in message["fields"]], ["From", "To", "Amount"])

    def test_edit_validator_only_exposes_fields_that_actually_change(self):
        description = (field(1, "[do-not-modify]") + field(2, "[do-not-modify]")
                       + field(3, "[do-not-modify]") + field(4, "[do-not-modify]")
                       + field(5, "Professional validator and infrastructure provider"))
        payload = field(1, description) + field(2, "atonevaloper1validator")
        message = normalize([("/cosmos.staking.v1beta1.MsgEditValidator", payload)])["messages"][0]
        self.assertEqual(message["action"], "Edit validator")
        self.assertEqual(message["fields"], [
            {"label": "Validator", "value": "atonevaloper1validator"},
            {"label": "Details", "value": "Professional validator and infrastructure provider"},
        ])
        self.assertNotIn("[do-not-modify]", str(message))

    def test_reward_and_commission_amounts_are_attached_to_the_correct_message(self):
        reward = field(1, "atone1delegator") + field(2, "atonevaloper1validator")
        commission = field(1, "atonevaloper1validator")
        detail = normalize([
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward),
            ("/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission", commission),
        ], events=[
            event("withdraw_rewards", {
                "amount": "12807843uphoton",
                "validator": "atonevaloper1validator",
                "delegator": "atone1delegator",
            }, 0),
            event("withdraw_commission", {"amount": "461236uphoton"}, 1),
        ])
        self.assertEqual(detail["messages"][0]["fields"][-1], {
            "label": "Reward withdrawn",
            "value": [{"denom": "uphoton", "amount": "12807843"}],
        })
        self.assertEqual(detail["messages"][1]["fields"][-1], {
            "label": "Commission withdrawn",
            "value": [{"denom": "uphoton", "amount": "461236"}],
        })

    def test_single_message_can_use_legacy_event_without_msg_index(self):
        reward = field(1, "atone1delegator") + field(2, "atonevaloper1validator")
        message = normalize([
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward),
        ], events=[event("withdraw_rewards", {"amount": "42uatone"})])["messages"][0]
        self.assertEqual(message["fields"][-1], {
            "label": "Reward withdrawn",
            "value": [{"denom": "uatone", "amount": "42"}],
        })

    def test_multi_message_legacy_events_without_msg_index_are_not_guessed(self):
        reward_a = field(1, "atone1a") + field(2, "atonevaloper1a")
        reward_b = field(1, "atone1b") + field(2, "atonevaloper1b")
        detail = normalize([
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward_a),
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward_b),
        ], events=[event("withdraw_rewards", {"amount": "999uatone"})])
        for message in detail["messages"]:
            self.assertNotIn("Reward withdrawn", [item["label"] for item in message["fields"]])

    def test_failed_transaction_does_not_claim_execution_amounts(self):
        reward = field(1, "atone1delegator") + field(2, "atonevaloper1validator")
        message = normalize([
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward),
        ], events=[event("withdraw_rewards", {"amount": "42uatone"})], code=7)["messages"][0]
        self.assertNotIn("Reward withdrawn", [item["label"] for item in message["fields"]])

    def test_validator_operational_messages_are_human_readable_and_multi_message_safe(self):
        reward = field(1, "atone1delegator") + field(2, "atonevaloper1validator")
        commission = field(1, "atonevaloper1validator")
        unjail = field(1, "atonevaloper1validator")
        detail = normalize([
            ("/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward", reward),
            ("/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission", commission),
            ("/cosmos.slashing.v1beta1.MsgUnjail", unjail),
        ])
        self.assertEqual(detail["message_count"], 3)
        self.assertEqual([message["action"] for message in detail["messages"]], [
            "Withdraw reward", "Withdraw validator commission", "Unjail",
        ])
        self.assertEqual(detail["messages"][1]["fields"], [
            {"label": "Validator", "value": "atonevaloper1validator"}
        ])

    def test_create_validator_decodes_nested_description_commission_and_value(self):
        description = field(1, "UTSA") + field(3, "https://example.com") + field(5, "Validator details")
        commission = field(1, "0.050000000000000000") + field(2, "0.250000000000000000") + field(3, "0.100000000000000000")
        payload = (field(1, description) + field(2, commission) + field(3, "1")
                   + field(4, "atone1delegator") + field(5, "atonevaloper1validator")
                   + field(7, coin("1000000")))
        message = normalize([("/cosmos.staking.v1beta1.MsgCreateValidator", payload)])["messages"][0]
        labels = [item["label"] for item in message["fields"]]
        self.assertEqual(labels, ["Validator", "Delegator", "Amount", "Minimum self delegation", "Moniker", "Website", "Details",
                                  "Commission rate", "Maximum commission", "Maximum daily change"])
        self.assertEqual(message["fields"][2]["value"], {"denom": "uatone", "amount": "1000000"})

    def test_weighted_vote_and_deposit_keep_structured_safe_details(self):
        yes = field(1, 1) + field(2, "0.700000000000000000")
        abstain = field(1, 2) + field(2, "0.300000000000000000")
        vote = field(1, 9) + field(2, "atone1voter") + field(3, yes) + field(3, abstain)
        deposit = field(1, 9) + field(2, "atone1depositor") + field(3, coin("42"))
        detail = normalize([
            ("/cosmos.gov.v1.MsgVoteWeighted", vote),
            ("/cosmos.gov.v1.MsgDeposit", deposit),
        ])
        options = detail["messages"][0]["fields"][2]["value"]
        self.assertEqual(options, [
            {"option": "Yes", "weight": "0.700000000000000000"},
            {"option": "Abstain", "weight": "0.300000000000000000"},
        ])
        self.assertEqual(detail["messages"][1]["fields"][2]["value"], [{"denom": "uatone", "amount": "42"}])


if __name__ == "__main__":
    unittest.main()
