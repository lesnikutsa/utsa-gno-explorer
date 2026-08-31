"""Bounded block-context Cosmos transaction decoding without transaction indexing."""

import base64
import hashlib

from .errors import MalformedUpstreamResponse
from .parsing import _height, _identity, _mapping, _timestamp

MAX_TX_BYTES = 2_000_000
MAX_FIELDS = 256


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


_MESSAGES = {
    "/cosmos.bank.v1beta1.MsgSend": ("Send", ((1, "From", "text"), (2, "To", "text"), (3, "Amount", "coins"))),
    "/cosmos.staking.v1beta1.MsgDelegate": ("Delegate", ((1, "Delegator", "text"), (2, "Validator", "text"), (3, "Amount", "coin"))),
    "/cosmos.staking.v1beta1.MsgUndelegate": ("Undelegate", ((1, "Delegator", "text"), (2, "Validator", "text"), (3, "Amount", "coin"))),
    "/cosmos.staking.v1beta1.MsgBeginRedelegate": ("Redelegate", ((1, "Delegator", "text"), (2, "Source validator", "text"), (3, "Destination validator", "text"), (4, "Amount", "coin"))),
    "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward": ("Withdraw reward", ((1, "Delegator", "text"), (2, "Validator", "text"))),
    "/cosmos.gov.v1beta1.MsgVote": ("Vote", ((1, "Proposal", "uint"), (2, "Voter", "text"), (3, "Option", "uint"))),
    "/ibc.applications.transfer.v1.MsgTransfer": ("IBC transfer", ((1, "Source port", "text"), (2, "Source channel", "text"), (3, "Token", "coin"), (4, "Sender", "text"), (5, "Receiver", "text"))),
}


def _message(raw_any):
    any_fields = _fields(raw_any)
    type_url, value = _text(_one(any_fields, 1)), _one(any_fields, 2)
    if not type_url or not type_url.startswith("/") or value is None:
        raise MalformedUpstreamResponse("invalid Cosmos message Any")
    specification = _MESSAGES.get(type_url)
    if not specification:
        return {"type_url": type_url, "action": type_url.rsplit(".", 1)[-1].removeprefix("Msg"), "fields": []}
    action, definitions = specification
    fields = _fields(value)
    normalized = []
    for number, label, kind in definitions:
        values = [item for field, wire, item in fields if field == number and wire == (0 if kind == "uint" else 2)]
        if kind == "text": parsed = _text(values[0]) if len(values) == 1 else None
        elif kind == "uint": parsed = str(values[0]) if len(values) == 1 else None
        elif kind == "coin": parsed = _coin(values[0]) if len(values) == 1 else None
        else: parsed = [coin for coin in (_coin(item) for item in values) if coin]
        if parsed not in (None, []): normalized.append({"label": label, "value": parsed})
    return {"type_url": type_url, "action": action, "fields": normalized}


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
