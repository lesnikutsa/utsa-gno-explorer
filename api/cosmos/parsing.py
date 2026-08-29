"""Strict parsers for the small accepted CometBFT/Cosmos response subset."""

from datetime import datetime, timezone
import re

from .errors import MalformedUpstreamResponse, RejectedEndpoint
from .models import BlockSummary, ChainHead

_HEX = re.compile(r"^[0-9A-Fa-f]+$")


def _mapping(value: object) -> dict:
    if not isinstance(value, dict):
        raise MalformedUpstreamResponse("upstream field is not an object")
    return value


def _text(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip() or not value.isprintable():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _height(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse("invalid height")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 20):
        raise MalformedUpstreamResponse("invalid height")
    height = int(value)
    if height <= 0 or height > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse("invalid height")
    return height


def _timestamp(value: object) -> str:
    text = _text(value, "timestamp", 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MalformedUpstreamResponse("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise MalformedUpstreamResponse("invalid timestamp")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hex(value: object, name: str, maximum: int) -> str:
    text = _text(value, name, maximum)
    if len(text) % 2 or not _HEX.fullmatch(text):
        raise MalformedUpstreamResponse(f"invalid {name}")
    return text.upper()


def _identity(actual: object, expected: str) -> str:
    chain_id = _text(actual, "runtime chain ID", 128)
    if chain_id != expected:
        raise RejectedEndpoint("wrong_chain")
    return chain_id


def parse_rpc_status(payload: dict, *, network_id: str, expected_chain_id: str, source_host: str) -> ChainHead:
    result = _mapping(_mapping(payload).get("result"))
    sync = _mapping(result.get("sync_info"))
    node_info = _mapping(result.get("node_info"))
    chain_id = _identity(node_info.get("network"), expected_chain_id)
    catching_up = sync.get("catching_up")
    if type(catching_up) is not bool:
        raise MalformedUpstreamResponse("invalid catching-up status")
    return ChainHead(network_id, chain_id, _height(sync.get("latest_block_height")),
                     _timestamp(sync.get("latest_block_time")), catching_up, source_host)


def _rest_block(payload: dict) -> tuple[dict, dict]:
    block = _mapping(_mapping(payload).get("block"))
    return block, _mapping(block.get("header"))


def parse_rest_head(payload: dict, *, network_id: str, expected_chain_id: str, source_host: str) -> ChainHead:
    _block, header = _rest_block(payload)
    chain_id = _identity(header.get("chain_id"), expected_chain_id)
    return ChainHead(network_id, chain_id, _height(header.get("height")), _timestamp(header.get("time")), False, source_host)


def parse_rest_block(payload: dict, *, network_id: str, expected_chain_id: str) -> BlockSummary:
    payload = _mapping(payload)
    block, header = _rest_block(payload)
    chain_id = _identity(header.get("chain_id"), expected_chain_id)
    txs = _mapping(block.get("data")).get("txs")
    if txs is None:
        txs = []
    if not isinstance(txs, list) or len(txs) > 1_000_000:
        raise MalformedUpstreamResponse("invalid transaction list")
    return BlockSummary(network_id, chain_id, _height(header.get("height")),
                        _hex(_mapping(payload.get("block_id")).get("hash"), "block hash", 128),
                        _timestamp(header.get("time")),
                        _hex(header.get("proposer_address"), "proposer address", 128), len(txs))


def parse_rpc_block(payload: dict, *, network_id: str, expected_chain_id: str) -> BlockSummary:
    result = _mapping(_mapping(payload).get("result"))
    block = _mapping(result.get("block"))
    header = _mapping(block.get("header"))
    chain_id = _identity(header.get("chain_id"), expected_chain_id)
    txs = _mapping(block.get("data")).get("txs")
    if txs is None:
        txs = []
    if not isinstance(txs, list) or len(txs) > 1_000_000:
        raise MalformedUpstreamResponse("invalid transaction list")
    return BlockSummary(network_id, chain_id, _height(header.get("height")),
                        _hex(_mapping(result.get("block_id")).get("hash"), "block hash", 128),
                        _timestamp(header.get("time")),
                        _hex(header.get("proposer_address"), "proposer address", 128), len(txs))
