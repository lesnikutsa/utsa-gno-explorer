import base64
import hashlib
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.schemas import TransactionDetailResponse
from api.cosmos.transaction_detail import normalize_transaction_detail
from api.cosmos.service import CosmosService

TIME = "2026-08-31T11:12:28Z"


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def field(number, value):
    if isinstance(value, int): return varint(number << 3) + varint(value)
    if isinstance(value, str): value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def coin(amount="1234567", denom="uatone"):
    return field(1, denom) + field(2, amount)


def tx(message_type="/cosmos.bank.v1beta1.MsgSend", message=None):
    message = message or field(1, "atone1from") + field(2, "atone1to") + field(3, coin())
    any_message = field(1, message_type) + field(2, message)
    body = field(1, any_message) + field(2, "memo")
    fee = field(1, coin("5000")) + field(2, 200000)
    auth = field(2, fee)
    return field(1, body) + field(2, auth) + field(3, b"signature")


def payloads(raw=None, result=None, txs=None):
    raw = tx() if raw is None else raw
    encoded = base64.b64encode(raw).decode()
    txs = [encoded] if txs is None else txs
    block = {"result": {"block": {"header": {"chain_id": "atomone-1", "height": "10", "time": TIME}, "data": {"txs": txs}}}}
    results = {"result": {"height": "10", "txs_results": [result or {"code": 0, "gas_used": "84321", "gas_wanted": "90000"}] if txs else []}}
    return block, results


def normalize(*items, index=0):
    return normalize_transaction_detail(*items, expected_chain_id="atomone-1", requested_height=10, tx_index=index)


def test_valid_transaction_is_decoded_from_block_context():
    raw = tx(); detail = normalize(*payloads(raw))
    assert detail["tx_hash"] == hashlib.sha256(raw).hexdigest().upper()
    assert (detail["height"], detail["index"], detail["timestamp"]) == (10, 0, "2026-08-31T11:12:28.000000Z")
    assert (detail["gas_used"], detail["gas_wanted"], detail["memo"]) == (84321, 90000, "memo")
    assert detail["fee"] == {"amount": [{"denom": "uatone", "amount": "5000"}], "gas_limit": 200000}
    assert detail["messages"][0]["action"] == "Send"
    assert [item["label"] for item in detail["messages"][0]["fields"]] == ["From", "To", "Amount"]
    TransactionDetailResponse.model_validate(detail)


def test_failed_transaction_and_unknown_message_fallback():
    raw = tx("/custom.module.v1.MsgMystery", field(1, "opaque"))
    detail = normalize(*payloads(raw, {"code": 7, "gas_used": "2", "gas_wanted": "3"}))
    assert not detail["success"] and detail["code"] == 7
    assert detail["messages"] == [{"type_url": "/custom.module.v1.MsgMystery", "action": "Mystery", "fields": []}]


def test_out_of_range_empty_block_and_malformed_bytes():
    with pytest.raises(IndexError): normalize(*payloads(), index=1)
    with pytest.raises(IndexError): normalize(*payloads(txs=[]))
    block, results = payloads(b"\x0a\xff")
    with pytest.raises(MalformedUpstreamResponse): normalize(block, results)


def test_service_fails_over_from_malformed_rpc_candidate():
    block, results = payloads()
    class Cache:
        async def get_or_load(self, _key, _ttl, load): return await load()
    class Transport:
        async def get_object(self, endpoint, path):
            payload = deepcopy(block if path.startswith("/block?") else results)
            if endpoint == "https://bad.example" and path.startswith("/block?"):
                payload["result"]["block"]["header"]["chain_id"] = "wrong-1"
            return payload
    async def run():
        service = object.__new__(CosmosService)
        service.definition = SimpleNamespace(transport=SimpleNamespace(network_id="atomone-mainnet", chain_id="atomone-1"))
        service.cache = Cache(); service.transport = Transport()
        service._status_observations = lambda: asyncio.sleep(0, result=[
            ("https://bad.example", SimpleNamespace(local_height=12)),
            ("https://good.example", SimpleNamespace(local_height=11))])
        return await service.transaction_detail(10, 0)
    assert asyncio.run(run())["messages"][0]["action"] == "Send"
