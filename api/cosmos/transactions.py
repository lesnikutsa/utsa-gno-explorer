"""Bounded normalization for Cosmos SDK REST transaction search."""

import re

from .errors import MalformedUpstreamResponse

MAX_TXS = 20
_HASH = re.compile(r"^[0-9A-Fa-f]{64}$")
_ACTIONS = {
    "/cosmos.bank.v1beta1.MsgSend": "Send",
    "/cosmos.staking.v1beta1.MsgDelegate": "Delegate",
    "/cosmos.staking.v1beta1.MsgUndelegate": "Undelegate",
    "/cosmos.staking.v1beta1.MsgBeginRedelegate": "Redelegate",
    "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward": "Withdraw reward",
    "/cosmos.gov.v1beta1.MsgVote": "Vote",
    "/ibc.applications.transfer.v1.MsgTransfer": "IBC transfer",
}


def _uint(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
        raise MalformedUpstreamResponse(f"invalid {name}")
    number = int(value)
    if number < 0 or number > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return number


def _type(message):
    if not isinstance(message, dict):
        raise MalformedUpstreamResponse("invalid transaction message")
    value = message.get("@type")
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 256:
        raise MalformedUpstreamResponse("invalid transaction message type")
    return value


def normalize_transactions(payload, limit):
    if type(limit) is not int or not 1 <= limit <= MAX_TXS or not isinstance(payload, dict):
        raise MalformedUpstreamResponse("invalid transaction response")
    txs, responses = payload.get("txs"), payload.get("tx_responses")
    if not isinstance(txs, list) or not isinstance(responses, list) or len(txs) != len(responses) or len(txs) > limit:
        raise MalformedUpstreamResponse("invalid transaction result")
    rows = []
    for tx, response in zip(txs, responses):
        if not isinstance(tx, dict) or not isinstance(response, dict):
            raise MalformedUpstreamResponse("invalid transaction")
        tx_hash = response.get("txhash")
        timestamp = response.get("timestamp")
        body, auth = tx.get("body"), tx.get("auth_info")
        if not _HASH.fullmatch(tx_hash or "") or not isinstance(timestamp, str) or len(timestamp) > 64:
            raise MalformedUpstreamResponse("invalid transaction identity")
        if not isinstance(body, dict) or not isinstance(auth, dict) or not isinstance(body.get("messages"), list):
            raise MalformedUpstreamResponse("invalid decoded transaction")
        types = [_type(message) for message in body["messages"]]
        fee = auth.get("fee")
        amounts = fee.get("amount", []) if isinstance(fee, dict) else []
        coin = amounts[0] if isinstance(amounts, list) and len(amounts) == 1 and isinstance(amounts[0], dict) else None
        fee_amount = coin.get("amount") if coin else None
        fee_denom = coin.get("denom") if coin else None
        if fee_amount is not None and (not isinstance(fee_amount, str) or not fee_amount.isdigit()):
            fee_amount = fee_denom = None
        sender = next((message.get(key) for message in body["messages"] for key in
                       ("from_address", "delegator_address", "sender", "voter")
                       if isinstance(message.get(key), str)), None)
        primary = types[0] if types else None
        rows.append({"tx_hash": tx_hash.upper(), "height": _uint(response.get("height"), "height"),
            "timestamp": timestamp, "success": _uint(response.get("code", 0), "code") == 0,
            "code": _uint(response.get("code", 0), "code"),
            "gas_wanted": _uint(response.get("gas_wanted"), "gas wanted"),
            "gas_used": _uint(response.get("gas_used"), "gas used"),
            "fee_amount": fee_amount, "fee_denom": fee_denom,
            "memo": body.get("memo") if isinstance(body.get("memo"), str) and len(body["memo"]) <= 1024 else None,
            "message_count": len(types), "primary_message_type": primary,
            "primary_action": _ACTIONS.get(primary, primary.rsplit(".", 1)[-1].removeprefix("Msg") if primary else "Unknown"),
            "sender": sender})
    pagination = payload.get("pagination")
    legacy_total = pagination.get("total") if isinstance(pagination, dict) else None
    modern_total = payload.get("total")
    if modern_total is not None and legacy_total is not None:
        modern_value = _uint(modern_total, "transaction total")
        legacy_value = _uint(legacy_total, "pagination total")
        if modern_value != legacy_value:
            raise MalformedUpstreamResponse("conflicting transaction totals")
        total = modern_value
    elif modern_total is not None:
        total = _uint(modern_total, "transaction total")
    elif legacy_total is not None:
        total = _uint(legacy_total, "pagination total")
    else:
        total = None
    return rows, total
