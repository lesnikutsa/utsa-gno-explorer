"""Bounded transaction activity for Cosmos account pages."""

from __future__ import annotations

import asyncio
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import MalformedUpstreamResponse
from .rfc3339 import normalize_rfc3339


MAX_ACCOUNT_ACTIVITY = 50
_HASH = re.compile(r"^[0-9A-Fa-f]{64}$")
_EVENT_COIN = re.compile(r"^([0-9]+)([A-Za-z][A-Za-z0-9/:._-]{0,127})$")

MSG_SEND = "/cosmos.bank.v1beta1.MsgSend"
MSG_DELEGATE = "/cosmos.staking.v1beta1.MsgDelegate"
MSG_UNDELEGATE = "/cosmos.staking.v1beta1.MsgUndelegate"
MSG_REDELEGATE = "/cosmos.staking.v1beta1.MsgBeginRedelegate"
MSG_CANCEL_UNBONDING = "/cosmos.staking.v1beta1.MsgCancelUnbondingDelegation"
MSG_WITHDRAW_REWARD = "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"
MSG_SET_WITHDRAW = "/cosmos.distribution.v1beta1.MsgSetWithdrawAddress"
MSG_FUND_POOL = "/cosmos.distribution.v1beta1.MsgFundCommunityPool"
MSG_VOTE = {"/cosmos.gov.v1.MsgVote", "/cosmos.gov.v1beta1.MsgVote",
            "/cosmos.gov.v1.MsgVoteWeighted", "/cosmos.gov.v1beta1.MsgVoteWeighted"}
MSG_DEPOSIT = {"/cosmos.gov.v1.MsgDeposit", "/cosmos.gov.v1beta1.MsgDeposit"}
MSG_IBC_TRANSFER = "/ibc.applications.transfer.v1.MsgTransfer"
MSG_IBC_RECV_PACKET = "/ibc.core.channel.v1.MsgRecvPacket"
MSG_AUTHZ_EXEC = "/cosmos.authz.v1beta1.MsgExec"
MSG_AUTHZ_GRANT = "/cosmos.authz.v1beta1.MsgGrant"
MSG_AUTHZ_REVOKE = "/cosmos.authz.v1beta1.MsgRevoke"
MSG_CREATE_VALIDATOR = "/cosmos.staking.v1beta1.MsgCreateValidator"
MSG_EDIT_VALIDATOR = "/cosmos.staking.v1beta1.MsgEditValidator"
MSG_UNJAIL = "/cosmos.slashing.v1beta1.MsgUnjail"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CosmosAccountActivityCoin(StrictModel):
    denom: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=128, pattern=r"^[0-9]+$")


class CosmosAccountActivityItem(StrictModel):
    tx_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9A-F]{64}$")
    height: int = Field(gt=0)
    message_index: int = Field(ge=0, le=99)
    timestamp: str = Field(min_length=20, max_length=64)
    success: bool
    action: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    direction: Literal["positive", "negative", "neutral"]
    amounts: list[CosmosAccountActivityCoin] = Field(default_factory=list, max_length=32)
    detail: str | None = Field(default=None, max_length=256)
    type_url: str | None = Field(default=None, max_length=256)


class CosmosAccountActivityResponse(StrictModel):
    state: Literal["available", "partial", "indexing_unavailable"]
    items: list[CosmosAccountActivityItem] = Field(max_length=10)
    page: int = Field(ge=1, le=5)
    page_size: int = Field(ge=1, le=10)
    has_more: bool


def event_queries(address: str):
    """Keep account history bounded to authored and received transfers."""
    return (("message.sender", address), ("transfer.recipient", address))


def _coin(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MalformedUpstreamResponse("invalid activity coin")
    denom, amount = value.get("denom"), value.get("amount")
    if (not isinstance(denom, str) or not 1 <= len(denom) <= 128 or not denom.isprintable()
            or not isinstance(amount, str) or not amount or len(amount) > 128
            or not amount.isascii() or not amount.isdigit()):
        raise MalformedUpstreamResponse("invalid activity coin")
    return {"denom": denom, "amount": amount}


def _coins(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 32:
        raise MalformedUpstreamResponse("invalid activity coins")
    return [_coin(item) for item in value]


def _event_coins(value: object) -> list[dict[str, str]]:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return []
    result = []
    for part in value.split(","):
        match = _EVENT_COIN.fullmatch(part.strip())
        if not match:
            return []
        amount, denom = match.groups()
        result.append({"denom": denom, "amount": amount})
    return result


def _event_values(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or not isinstance(event.get("attributes"), list):
        return {}
    return {item.get("key"): item.get("value") for item in event["attributes"] if isinstance(item, dict)}


def _response_events(response: dict):
    """Yield decoded Cosmos events from both legacy logs and the v0.50 TxResponse event list."""
    logs = response.get("logs")
    if isinstance(logs, list):
        for log in logs:
            if not isinstance(log, dict) or not isinstance(log.get("events"), list):
                continue
            yield from (event for event in log["events"] if isinstance(event, dict))
    events = response.get("events")
    if isinstance(events, list):
        yield from (event for event in events if isinstance(event, dict))


def _withdrawal_amounts(response: dict, message_index: int, validator: str) -> list[dict[str, str]]:
    logs = response.get("logs")
    if not isinstance(logs, list):
        return []
    log = next((item for item in logs if isinstance(item, dict)
                and item.get("msg_index") in (message_index, str(message_index))), None)
    if not log or not isinstance(log.get("events"), list):
        return []
    for event in log["events"]:
        if not isinstance(event, dict) or event.get("type") != "withdraw_rewards":
            continue
        values = _event_values(event)
        if values.get("validator") != validator:
            continue
        coins = _event_coins(values.get("amount"))
        if coins:
            return coins
    return []


def _received_event_amounts(response: dict, address: str) -> list[dict[str, str]]:
    for event in _response_events(response):
        if event.get("type") != "transfer":
            continue
        values = _event_values(event)
        if values.get("recipient") == address:
            coins = _event_coins(values.get("amount"))
            if coins:
                return coins
    return []


def _text(value: object, maximum: int = 256) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= maximum and value.isprintable() else None


def _proposal(value: object) -> str | None:
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 20:
        return value
    return None


def _message_activity(message: dict, address: str, response: dict, index: int):
    kind = message.get("@type")
    if not isinstance(kind, str) or not kind.startswith("/") or len(kind) > 256:
        return None

    if kind == MSG_SEND:
        sender, recipient = message.get("from_address"), message.get("to_address")
        if sender == address or recipient == address:
            amounts = _coins(message.get("amount"))
            if sender == address and recipient == address:
                return "self_transfer", "neutral", amounts, "Self transfer", kind
            if sender == address:
                return "sent", "negative", amounts, _text(recipient, 90), kind
            return "received", "positive", amounts, _text(sender, 90), kind

    if kind in (MSG_DELEGATE, MSG_UNDELEGATE, MSG_CANCEL_UNBONDING):
        if message.get("delegator_address") != address:
            return None
        action = {MSG_DELEGATE: "delegate", MSG_UNDELEGATE: "undelegate",
                  MSG_CANCEL_UNBONDING: "cancel_unbonding"}[kind]
        direction = "positive" if kind in (MSG_DELEGATE, MSG_CANCEL_UNBONDING) else "negative"
        amount = _coin(message.get("amount"))
        return action, direction, [amount], _text(message.get("validator_address"), 90), kind

    if kind == MSG_REDELEGATE and message.get("delegator_address") == address:
        amount = _coin(message.get("amount"))
        source = _text(message.get("validator_src_address"), 90)
        destination = _text(message.get("validator_dst_address"), 90)
        detail = f"{source} → {destination}" if source and destination else source or destination
        return "redelegate", "neutral", [amount], detail, kind

    if kind == MSG_WITHDRAW_REWARD and message.get("delegator_address") == address:
        validator = _text(message.get("validator_address"), 90)
        amounts = _withdrawal_amounts(response, index, validator or "")
        return "withdraw_reward", "positive", amounts, validator, kind

    if kind == MSG_SET_WITHDRAW and message.get("delegator_address") == address:
        return "set_withdraw_address", "neutral", [], _text(message.get("withdraw_address"), 90), kind

    if kind == MSG_FUND_POOL and message.get("depositor") == address:
        return "fund_community_pool", "negative", _coins(message.get("amount")), None, kind

    if kind in MSG_VOTE and message.get("voter") == address:
        proposal = _proposal(message.get("proposal_id"))
        return "vote", "neutral", [], f"Proposal #{proposal}" if proposal is not None else None, kind

    if kind in MSG_DEPOSIT and message.get("depositor") == address:
        proposal = _proposal(message.get("proposal_id"))
        detail = f"Proposal #{proposal}" if proposal is not None else None
        return "deposit", "negative", _coins(message.get("amount")), detail, kind

    if kind == MSG_IBC_TRANSFER and message.get("sender") == address:
        token = _coin(message.get("token"))
        channel, receiver = _text(message.get("source_channel"), 128), _text(message.get("receiver"), 256)
        detail = " · ".join(item for item in (channel, receiver) if item) or None
        return "ibc_transfer", "negative", [token], detail, kind

    if kind == MSG_AUTHZ_EXEC and message.get("grantee") == address:
        return "authz_execution", "neutral", [], None, kind
    if kind == MSG_AUTHZ_GRANT and message.get("granter") == address:
        return "grant_authorization", "neutral", [], _text(message.get("grantee"), 90), kind
    if kind == MSG_AUTHZ_REVOKE and message.get("granter") == address:
        return "revoke_authorization", "neutral", [], _text(message.get("grantee"), 90), kind

    if kind == MSG_CREATE_VALIDATOR and message.get("delegator_address") == address:
        amount = _coin(message.get("value")) if isinstance(message.get("value"), dict) else None
        return "create_validator", "neutral", [amount] if amount else [], _text(message.get("validator_address"), 90), kind

    if kind in (MSG_EDIT_VALIDATOR, MSG_UNJAIL):
        return "validator_operation", "neutral", [], None, kind

    return None


def _ibc_received_activity(messages: list[dict], response: dict, address: str):
    """Prefer the actual receive-packet message over a relayer's preceding update-client message."""
    for index, message in enumerate(messages):
        if message.get("@type") != MSG_IBC_RECV_PACKET:
            continue
        packet = message.get("packet")
        source = destination = None
        if isinstance(packet, dict):
            source = _text(packet.get("source_channel"), 128)
            destination = _text(packet.get("destination_channel"), 128)
        detail = f"{source} → {destination}" if source and destination else source or destination
        return (index, "ibc_received", "positive", _received_event_amounts(response, address),
                detail, MSG_IBC_RECV_PACKET)
    return None


def normalize_transaction(tx: object, response: object, address: str, event_key: str):
    if not isinstance(tx, dict) or not isinstance(response, dict):
        raise MalformedUpstreamResponse("invalid account transaction search result")
    body = tx.get("body")
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list) or len(messages) > 100:
        raise MalformedUpstreamResponse("invalid account transaction messages")
    tx_hash = response.get("txhash")
    if not isinstance(tx_hash, str) or _HASH.fullmatch(tx_hash) is None:
        raise MalformedUpstreamResponse("invalid account transaction hash")
    try:
        height = int(response.get("height"))
    except (TypeError, ValueError):
        raise MalformedUpstreamResponse("invalid account transaction height") from None
    timestamp = response.get("timestamp")
    if not isinstance(timestamp, str) or not 20 <= len(timestamp) <= 64:
        raise MalformedUpstreamResponse("invalid account transaction timestamp")
    try:
        timestamp = normalize_rfc3339(timestamp)
    except ValueError:
        raise MalformedUpstreamResponse("invalid account transaction timestamp") from None
    if not 1 <= height <= 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse("invalid account transaction height")

    selected = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise MalformedUpstreamResponse("invalid account transaction message")
        candidate = _message_activity(message, address, response, index)
        if candidate is not None:
            selected = (index, *candidate)
            break

    if selected is None:
        if event_key == "transfer.recipient":
            selected = _ibc_received_activity(messages, response, address)
            if selected is None:
                selected = (0, "received", "positive", _received_event_amounts(response, address), None,
                            _text(messages[0].get("@type"), 256) if messages else None)
        else:
            selected = (0, "transaction", "neutral", [], None,
                        _text(messages[0].get("@type"), 256) if messages else None)

    index, action, direction, amounts, detail, type_url = selected
    success = response.get("code", 0) in (0, "0", None)
    if not success:
        amounts, direction = [], "neutral"
    return {
        "tx_hash": tx_hash.upper(), "height": height, "message_index": index,
        "timestamp": timestamp, "success": success, "action": action,
        "direction": direction, "amounts": amounts, "detail": detail, "type_url": type_url,
    }


def merge_account_activity(results: list[tuple[str, dict]], address: str):
    items = {}
    for event_key, payload in results:
        txs, responses = payload.get("txs"), payload.get("tx_responses")
        if not isinstance(txs, list) or not isinstance(responses, list) or len(txs) != len(responses):
            raise MalformedUpstreamResponse("invalid account transaction search response")
        for tx, response in zip(txs, responses):
            item = normalize_transaction(tx, response, address, event_key)
            current = items.get(item["tx_hash"])
            if current is None or (current["action"] == "transaction" and item["action"] != "transaction"):
                items[item["tx_hash"]] = item
    return sorted(items.values(), key=lambda item: (-item["height"], item["tx_hash"]))[:MAX_ACCOUNT_ACTIVITY]


async def load_account_activity(service, address: str, limit: int = 10, page: int = 1) -> dict:
    from .service import valid_bech32_address

    if not valid_bech32_address(address, service.definition.account_prefix):
        raise ValueError("invalid account address")
    if type(limit) is not int or not 1 <= limit <= 10 or type(page) is not int or not 1 <= page <= 5:
        raise ValueError("invalid activity pagination")

    upstream_limit = min(MAX_ACCOUNT_ACTIVITY, page * limit + 1)
    queries = event_queries(address)

    async def search(event_key, value):
        return event_key, await service._validator_event_search(f"{event_key}='{value}'", upstream_limit)

    outcomes = await asyncio.gather(*(search(*query) for query in queries), return_exceptions=True)
    successful = []
    for outcome in outcomes:
        if not isinstance(outcome, tuple) or len(outcome) != 2 or not isinstance(outcome[1], dict):
            continue
        try:
            merge_account_activity([outcome], address)
            successful.append(outcome)
        except MalformedUpstreamResponse:
            continue

    if not successful:
        result = {"state": "indexing_unavailable", "items": [], "page": page,
                  "page_size": limit, "has_more": False}
    else:
        items = merge_account_activity(successful, address)
        start = (page - 1) * limit
        result = {"state": "partial" if len(successful) < len(queries) else "available",
                  "items": items[start:start + limit], "page": page,
                  "page_size": limit, "has_more": start + limit < len(items)}
    return CosmosAccountActivityResponse.model_validate(result, strict=True).model_dump()