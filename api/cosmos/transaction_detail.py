"""Bounded block-context Cosmos transaction decoding without transaction indexing."""

import base64
import hashlib
import re

from .errors import MalformedUpstreamResponse
from .parsing import _height, _identity, _mapping, _timestamp

MAX_TX_BYTES = 2_000_000
MAX_FIELDS = 256
_DO_NOT_MODIFY = "[do-not-modify]"
_VOTE_OPTIONS = {
    0: "Unspecified",
    1: "Yes",
    2: "Abstain",
    3: "No",
    4: "No with veto",
}
_EVENT_COIN_RE = re.compile(r"^([0-9]+)([A-Za-z][A-Za-z0-9/:._-]{0,127})$")


def _varint(data, offset):
    value = shift = 0
    for _ in range(10):
        if offset >= len(data):
            raise MalformedUpstreamResponse("truncated protobuf varint")
        byte = data[offset]; offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
        shift += 7
    raise MalformedUpstreamResponse("invalid protobuf varint")


def _fields(data):
    if not isinstance(data, bytes) or len(data) > MAX_TX_BYTES:
        raise MalformedUpstreamResponse("invalid transaction bytes")
    result = []
    offset = 0
    while offset < len(data):
        if len(result) >= MAX_FIELDS:
            raise MalformedUpstreamResponse("too many protobuf fields")
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise MalformedUpstreamResponse("invalid protobuf field")
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire == 2:
            length, offset = _varint(data, offset)
            if length > MAX_TX_BYTES or offset + length > len(data):
                raise MalformedUpstreamResponse("invalid protobuf length")
            value = data[offset:offset + length]; offset += length
        else:
            raise MalformedUpstreamResponse("unsupported protobuf wire type")
        result.append((number, wire, value))
    return result


def _one(fields, number, wire=2):
    values = [value for field, kind, value in fields if field == number and kind == wire]
    return values[0] if len(values) == 1 else None


def _text(value):
    if value is None:
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if len(decoded) <= 1024 and decoded.isprintable() else None


def _coin(raw):
    fields = _fields(raw)
    denom, amount = _text(_one(fields, 1)), _text(_one(fields, 2))
    return {"denom": denom, "amount": amount} if denom and amount and amount.isdigit() else None


def _event_coins(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    result = []
    for part in value.split(","):
        match = _EVENT_COIN_RE.fullmatch(part.strip())
        if not match:
            return None
        amount, denom = match.groups()
        result.append({"denom": denom, "amount": amount})
    return result or None


def _event_attributes(event):
    attributes = event.get("attributes") if isinstance(event, dict) else None
    if not isinstance(attributes, list):
        return {}
    result = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        key, value = attribute.get("key"), attribute.get("value")
        if (isinstance(key, str) and 0 < len(key) <= 128
                and isinstance(value, str) and len(value) <= 4096):
            result.setdefault(key, value)
    return result


def _message_events(events, message_index, message_count):
    if not isinstance(events, list):
        return []
    result = []
    for event in events:
        if not isinstance(event, dict):
            continue
        attributes = _event_attributes(event)
        raw_index = attributes.get("msg_index")
        if raw_index is None:
            if message_count == 1:
                result.append(event)
            continue
        if raw_index == str(message_index):
            result.append(event)
    return result


def _execution_coin_field(events, event_type, label):
    for event in events:
        if event.get("type") != event_type:
            continue
        amount = _event_coins(_event_attributes(event).get("amount"))
        if amount:
            return {"label": label, "value": amount}
    return None


def _field(label, value):
    return {"label": label, "value": value}


def _description(raw, *, edit=False):
    if raw is None:
        return []
    fields = _fields(raw)
    result = []
    for number, label in ((1, "Moniker"), (2, "Identity"), (3, "Website"),
                          (4, "Security contact"), (5, "Details")):
        value = _text(_one(fields, number))
        if not value or (edit and value == _DO_NOT_MODIFY):
            continue
        result.append(_field(label, value))
    return result


def _commission_rates(raw):
    if raw is None:
        return []
    fields = _fields(raw)
    result = []
    for number, label in ((1, "Commission rate"), (2, "Maximum commission"),
                          (3, "Maximum daily change")):
        value = _text(_one(fields, number))
        if value:
            result.append(_field(label, value))
    return result


def _edit_validator(fields):
    result = []
    validator = _text(_one(fields, 2))
    if validator:
        result.append(_field("Validator", validator))
    result.extend(_description(_one(fields, 1), edit=True))
    commission = _text(_one(fields, 3))
    if commission:
        result.append(_field("Commission rate", commission))
    minimum = _text(_one(fields, 4))
    if minimum:
        result.append(_field("Minimum self delegation", minimum))
    return result


def _create_validator(fields):
    result = []
    delegator = _text(_one(fields, 4))
    validator = _text(_one(fields, 5))
    amount = _coin(_one(fields, 7)) if _one(fields, 7) is not None else None
    minimum = _text(_one(fields, 3))
    if validator:
        result.append(_field("Validator", validator))
    if delegator:
        result.append(_field("Delegator", delegator))
    if amount:
        result.append(_field("Amount", amount))
    if minimum:
        result.append(_field("Minimum self delegation", minimum))
    result.extend(_description(_one(fields, 1)))
    result.extend(_commission_rates(_one(fields, 2)))
    return result


def _weighted_vote(fields):
    result = []
    proposal = _one(fields, 1, 0)
    voter = _text(_one(fields, 2))
    if proposal is not None:
        result.append(_field("Proposal", str(proposal)))
    if voter:
        result.append(_field("Voter", voter))
    options = []
    for field, wire, raw in fields:
        if field != 3 or wire != 2:
            continue
        option_fields = _fields(raw)
        option = _one(option_fields, 1, 0)
        weight = _text(_one(option_fields, 2))
        if option is None or not weight:
            continue
        options.append({"option": _VOTE_OPTIONS.get(option, str(option)), "weight": weight})
    if options:
        result.append(_field("Options", options))
    return result


_MESSAGES = {
    "/cosmos.bank.v1beta1.MsgSend": ("Send", ((1, "From", "text"), (2, "To", "text"), (3, "Amount", "coins"))),
    "/cosmos.staking.v1beta1.MsgDelegate": ("Delegate", ((1, "Delegator", "text"), (2, "Validator", "text"), (3, "Amount", "coin"))),
    "/cosmos.staking.v1beta1.MsgUndelegate": ("Undelegate", ((1, "Delegator", "text"), (2, "Validator", "text"), (3, "Amount", "coin"))),
    "/cosmos.staking.v1beta1.MsgBeginRedelegate": ("Redelegate", ((1, "Delegator", "text"), (2, "Source validator", "text"), (3, "Destination validator", "text"), (4, "Amount", "coin"))),
    "/cosmos.staking.v1beta1.MsgCancelUnbondingDelegation": ("Cancel unbonding", ((1, "Delegator", "text"), (2, "Validator", "text"), (3, "Amount", "coin"), (4, "Creation height", "uint"))),
    "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward": ("Withdraw reward", ((1, "Delegator", "text"), (2, "Validator", "text"))),
    "/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission": ("Withdraw validator commission", ((1, "Validator", "text"),)),
    "/cosmos.distribution.v1beta1.MsgSetWithdrawAddress": ("Set withdraw address", ((1, "Delegator", "text"), (2, "Withdraw address", "text"))),
    "/cosmos.distribution.v1beta1.MsgFundCommunityPool": ("Fund community pool", ((1, "Amount", "coins"), (2, "Depositor", "text"))),
    "/cosmos.slashing.v1beta1.MsgUnjail": ("Unjail", ((1, "Validator", "text"),)),
    "/cosmos.gov.v1beta1.MsgVote": ("Vote", ((1, "Proposal", "uint"), (2, "Voter", "text"), (3, "Option", "vote_option"))),
    "/cosmos.gov.v1.MsgVote": ("Vote", ((1, "Proposal", "uint"), (2, "Voter", "text"), (3, "Option", "vote_option"))),
    "/cosmos.gov.v1beta1.MsgDeposit": ("Deposit", ((1, "Proposal", "uint"), (2, "Depositor", "text"), (3, "Amount", "coins"))),
    "/cosmos.gov.v1.MsgDeposit": ("Deposit", ((1, "Proposal", "uint"), (2, "Depositor", "text"), (3, "Amount", "coins"))),
    "/ibc.applications.transfer.v1.MsgTransfer": ("IBC transfer", ((1, "Source port", "text"), (2, "Source channel", "text"), (3, "Token", "coin"), (4, "Sender", "text"), (5, "Receiver", "text"))),
}

_CUSTOM_MESSAGES = {
    "/cosmos.staking.v1beta1.MsgEditValidator": ("Edit validator", _edit_validator),
    "/cosmos.staking.v1beta1.MsgCreateValidator": ("Create validator", _create_validator),
    "/cosmos.gov.v1beta1.MsgVoteWeighted": ("Weighted vote", _weighted_vote),
    "/cosmos.gov.v1.MsgVoteWeighted": ("Weighted vote", _weighted_vote),
}

_EXECUTION_COIN_EVENTS = {
    "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward": ("withdraw_rewards", "Reward withdrawn"),
    "/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission": ("withdraw_commission", "Commission withdrawn"),
}


def _message(raw_any):
    any_fields = _fields(raw_any)
    type_url, value = _text(_one(any_fields, 1)), _one(any_fields, 2)
    if not type_url or not type_url.startswith("/") or value is None:
        raise MalformedUpstreamResponse("invalid Cosmos message Any")
    fields = _fields(value)
    custom = _CUSTOM_MESSAGES.get(type_url)
    if custom:
        action, decoder = custom
        return {"type_url": type_url, "action": action, "fields": decoder(fields)}
    specification = _MESSAGES.get(type_url)
    if not specification:
        return {"type_url": type_url, "action": type_url.rsplit(".", 1)[-1].removeprefix("Msg"), "fields": []}
    action, definitions = specification
    normalized = []
    for number, label, kind in definitions:
        values = [item for field, wire, item in fields if field == number and wire == (0 if kind in ("uint", "vote_option") else 2)]
        if kind == "text":
            parsed = _text(values[0]) if len(values) == 1 else None
        elif kind == "uint":
            parsed = str(values[0]) if len(values) == 1 else None
        elif kind == "vote_option":
            parsed = _VOTE_OPTIONS.get(values[0], str(values[0])) if len(values) == 1 else None
        elif kind == "coin":
            parsed = _coin(values[0]) if len(values) == 1 else None
        else:
            parsed = [coin for coin in (_coin(item) for item in values) if coin]
        if parsed not in (None, []):
            normalized.append(_field(label, parsed))
    return {"type_url": type_url, "action": action, "fields": normalized}


def _enrich_messages_from_events(messages, events):
    message_count = len(messages)
    for message_index, message in enumerate(messages):
        specification = _EXECUTION_COIN_EVENTS.get(message["type_url"])
        if not specification:
            continue
        event_type, label = specification
        field = _execution_coin_field(_message_events(events, message_index, message_count), event_type, label)
        if field:
            message["fields"].append(field)


def normalize_transaction_detail(block_payload, results_payload, *, expected_chain_id,
                                 requested_height, tx_index):
    result = _mapping(_mapping(block_payload).get("result"))
    block = _mapping(result.get("block")); header = _mapping(block.get("header"))
    _identity(header.get("chain_id"), expected_chain_id)
    height = _height(header.get("height"))
    if height != requested_height:
        raise MalformedUpstreamResponse("wrong block height")
    txs = _mapping(block.get("data", {})).get("txs") or []
    if not isinstance(txs, list): raise MalformedUpstreamResponse("invalid transactions")
    if not 0 <= tx_index < len(txs): raise IndexError("transaction index out of range")
    encoded = txs[tx_index]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise MalformedUpstreamResponse("invalid transaction base64") from None
    results = _mapping(_mapping(results_payload).get("result"))
    if _height(results.get("height")) != height: raise MalformedUpstreamResponse("wrong block results height")
    tx_results = results.get("txs_results") or []
    if not isinstance(tx_results, list) or len(tx_results) != len(txs):
        raise MalformedUpstreamResponse("transaction results do not match transactions")
    outcome = _mapping(tx_results[tx_index]); code = int(outcome.get("code", 0))
    raw_fields = _fields(raw); body_raw, auth_raw = _one(raw_fields, 1), _one(raw_fields, 2)
    if body_raw is None or auth_raw is None: raise MalformedUpstreamResponse("invalid TxRaw")
    body = _fields(body_raw)
    messages = [_message(value) for field, wire, value in body if field == 1 and wire == 2]
    if code == 0:
        _enrich_messages_from_events(messages, outcome.get("events"))
    memo = _text(_one(body, 2)) or None
    auth = _fields(auth_raw); fee_raw = _one(auth, 2); fee = None
    if fee_raw is not None:
        fee_fields = _fields(fee_raw)
        coins = [coin for coin in (_coin(value) for field, wire, value in fee_fields if field == 1 and wire == 2) if coin]
        fee = {"amount": coins, "gas_limit": _one(fee_fields, 2, 0)}
    def gas(name):
        value = outcome.get(name)
        return int(value) if isinstance(value, (str, int)) and str(value).isdigit() else None
    return {"tx_hash": hashlib.sha256(raw).hexdigest().upper(), "height": height, "index": tx_index,
            "timestamp": _timestamp(header.get("time")), "success": code == 0, "code": code,
            "gas_wanted": gas("gas_wanted"), "gas_used": gas("gas_used"), "fee": fee,
            "memo": memo, "message_count": len(messages), "messages": messages}
