"""Bounded message-level normalization for Cosmos validator activity."""

from decimal import Decimal, InvalidOperation
import re

from .errors import MalformedUpstreamResponse

MAX_ACTIVITY = 50
EVENT_KEYS = (
    "delegate.validator", "unbond.validator", "redelegate.source_validator",
    "redelegate.destination_validator", "withdraw_rewards.validator", "message.sender",
)
_COIN = re.compile(r"^([0-9]+)([A-Za-z][A-Za-z0-9/:._-]{0,127})$")


def event_queries(operator_address: str, account_address: str):
    return tuple((key, account_address if key == "message.sender" else operator_address)
                 for key in EVENT_KEYS)


def _coins(value):
    if not isinstance(value, str):
        return []
    result = []
    for part in value.split(","):
        match = _COIN.fullmatch(part.strip())
        if not match:
            return []
        result.append({"denom": match.group(2), "amount": match.group(1)})
    return result


def _withdrawal_amounts(response, message_index):
    logs = response.get("logs")
    if not isinstance(logs, list):
        return []
    log = next((item for item in logs if isinstance(item, dict)
                and item.get("msg_index") in (message_index, str(message_index))), None)
    if not log or not isinstance(log.get("events"), list):
        return []
    candidates = []
    for event in log["events"]:
        if not isinstance(event, dict) or event.get("type") != "withdraw_rewards":
            continue
        for attribute in event.get("attributes", []):
            if isinstance(attribute, dict) and attribute.get("key") == "amount":
                parsed = _coins(attribute.get("value"))
                if parsed:
                    candidates.append(parsed)
    return candidates[0] if len(candidates) == 1 else []


def normalize_transaction(tx, response, operator_address, account_address):
    if not isinstance(tx, dict) or not isinstance(response, dict):
        raise MalformedUpstreamResponse("invalid transaction search result")
    if response.get("code", 0) not in (0, "0", None):
        return []
    body = tx.get("body")
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list) or len(messages) > 100:
        raise MalformedUpstreamResponse("invalid transaction messages")
    tx_hash, timestamp = response.get("txhash"), response.get("timestamp")
    try:
        height = int(response.get("height"))
    except (TypeError, ValueError):
        raise MalformedUpstreamResponse("invalid transaction height") from None
    if not isinstance(tx_hash, str) or not tx_hash or height < 1 or not isinstance(timestamp, str):
        raise MalformedUpstreamResponse("invalid transaction identity")
    result = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise MalformedUpstreamResponse("invalid transaction message")
        kind = message.get("@type", "").rsplit(".", 1)[-1]
        action = direction = address = detail = None
        amounts = []
        if kind == "MsgDelegate" and message.get("validator_address") == operator_address:
            action, direction, address, amounts = "delegate", "positive", message.get("delegator_address"), [message.get("amount")]
        elif kind == "MsgUndelegate" and message.get("validator_address") == operator_address:
            action, direction, address, amounts = "undelegate", "negative", message.get("delegator_address"), [message.get("amount")]
        elif kind == "MsgBeginRedelegate":
            source, destination = message.get("validator_src_address"), message.get("validator_dst_address")
            if source == operator_address:
                action, direction = "redelegate_out", "negative"
            elif destination == operator_address:
                action, direction = "redelegate_in", "positive"
            if action:
                address, amounts = message.get("delegator_address"), [message.get("amount")]
        elif kind == "MsgWithdrawDelegatorReward" and message.get("validator_address") == operator_address:
            action, direction, address = "withdraw_reward", "neutral", message.get("delegator_address")
            amounts = _withdrawal_amounts(response, index)
        elif kind == "MsgWithdrawValidatorCommission" and message.get("validator_address") == operator_address:
            action, direction, address = "withdraw_commission", "neutral", account_address
            amounts = _withdrawal_amounts(response, index)
        elif kind == "MsgEditValidator" and message.get("validator_address") == operator_address:
            action, direction, address = "edit_validator", "neutral", account_address
            rate = message.get("commission_rate")
            try:
                detail = f"Commission → {Decimal(rate) * 100:.2f}%" if isinstance(rate, str) and rate else "Validator metadata updated"
            except InvalidOperation:
                detail = "Validator metadata updated"
        elif kind == "MsgUnjail" and message.get("validator_addr") == operator_address:
            action, direction, address = "unjail", "neutral", account_address
        if not action:
            continue
        clean_amounts = []
        for coin in amounts:
            if isinstance(coin, dict) and isinstance(coin.get("denom"), str) and isinstance(coin.get("amount"), str) and coin["amount"].isdigit():
                clean_amounts.append({"denom": coin["denom"], "amount": coin["amount"]})
        result.append({"tx_hash": tx_hash, "height": height, "message_index": index,
                       "timestamp": timestamp, "action": action, "account_address": address,
                       "direction": direction, "amounts": clean_amounts, "detail": detail})
    return result


def merge_activity(results, operator_address, account_address):
    items = {}
    for payload in results:
        txs, responses = payload.get("txs"), payload.get("tx_responses")
        if not isinstance(txs, list) or not isinstance(responses, list) or len(txs) != len(responses):
            raise MalformedUpstreamResponse("invalid transaction search response")
        for tx, response in zip(txs, responses):
            for item in normalize_transaction(tx, response, operator_address, account_address):
                key = (item["tx_hash"], item["message_index"], item["action"])
                items[key] = item
    return sorted(items.values(), key=lambda item: (-item["height"], item["tx_hash"], item["message_index"], item["action"]))[:MAX_ACTIVITY]
