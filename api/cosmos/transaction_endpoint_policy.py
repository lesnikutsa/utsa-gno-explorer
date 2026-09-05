"""Operation-aware automatic failover for Cosmos transaction endpoints."""

from __future__ import annotations

import time
from urllib.parse import quote

from pydantic import TypeAdapter, ValidationError

from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse, TransactionNotFound
from .schemas import CosmosTransactionsResponse
from .service_core import SECTION_TTL, _QUERY_FIELD_UNSUPPORTED, _integer, _mapping, _text
from .transactions import normalize_transactions

_TX_SUSPECT_SECONDS = 60.0
_TX_RECENT_BLOCK_WINDOW = 2_000


def _error_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    return " ".join(str(payload.get(key, "")) for key in ("message", "details", "error"))


def _index_unavailable(payload: object) -> bool:
    text = _error_text(payload).lower()
    return (("tx" in text or "transaction" in text)
            and ("index" in text or "search" in text)
            and any(marker in text for marker in (
                "disabled", "unavailable", "not enabled", "not configured", "no indexer")))


def _event_payload_valid(payload: object, limit: int) -> bool:
    if not isinstance(payload, dict):
        return False
    txs, responses, pagination = (payload.get("txs"), payload.get("tx_responses"),
                                  payload.get("pagination"))
    return (isinstance(txs, list) and isinstance(responses, list)
            and len(txs) == len(responses) and len(txs) <= limit
            and (pagination is None or isinstance(pagination, dict)))


class TransactionEndpointPolicyMixin:
    """Keep endpoint health scoped to the operation that actually failed.

    Basic REST/RPC probes still establish chain identity and freshness. This
    layer adds transaction-specific evidence so a fast endpoint that is fine
    for latest-block/status cannot suppress history from another endpoint.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tx_operation_suspect_until: dict[tuple[str, str], float] = {}
        self._tx_search_mode: dict[str, str] = {}

    def _operation_clock(self) -> float:
        clock = getattr(getattr(self, "adapter", None), "_clock", None)
        return clock() if callable(clock) else time.monotonic()

    async def _operation_candidates(self, kind: str, operation: str):
        candidates = list(await self.adapter._cached_candidates(kind))
        state = getattr(self, "_tx_operation_suspect_until", None)
        if state is None:
            state = self._tx_operation_suspect_until = {}
        now = self._operation_clock()
        for key, deadline in list(state.items()):
            if deadline <= now:
                state.pop(key, None)
        ordered = sorted(
            enumerate(candidates),
            key=lambda item: ((operation, item[1].endpoint) in state, item[0]),
        )
        return tuple(candidate for _index, candidate in ordered)

    def _mark_operation_suspect(self, operation: str, endpoint: str) -> None:
        state = getattr(self, "_tx_operation_suspect_until", None)
        if state is None:
            state = self._tx_operation_suspect_until = {}
        state[(operation, endpoint)] = self._operation_clock() + _TX_SUSPECT_SECONDS

    def _clear_operation_suspect(self, operation: str, endpoint: str) -> None:
        state = getattr(self, "_tx_operation_suspect_until", None)
        if state is not None:
            state.pop((operation, endpoint), None)

    async def _tx_search_payload(self, candidate, expression: str, page: int, limit: int):
        encoded = quote(expression, safe="")
        modern = (f"/cosmos/tx/v1beta1/txs?query={encoded}&order_by=ORDER_BY_DESC"
                  f"&page={page}&limit={limit}")
        legacy = (f"/cosmos/tx/v1beta1/txs?events={encoded}&order_by=ORDER_BY_DESC"
                  f"&page={page}&limit={limit}")
        modes = getattr(self, "_tx_search_mode", None)
        if modes is None:
            modes = self._tx_search_mode = {}
        if modes.get(candidate.endpoint) == "legacy":
            payload = await self.transport.get_object(
                candidate.endpoint, legacy, accept_error_payload=True)
            return payload, "legacy"
        payload = await self.transport.get_object(
            candidate.endpoint, modern, accept_error_payload=True)
        if _QUERY_FIELD_UNSUPPORTED.search(_error_text(payload)) is None:
            return payload, "modern"
        modes[candidate.endpoint] = "legacy"
        payload = await self.transport.get_object(
            candidate.endpoint, legacy, accept_error_payload=True)
        return payload, "legacy"

    async def _recent_transaction_expression(self) -> str:
        """Bound generic transaction search to a small recent block window."""
        status = await self.adapter.node_status()
        height = getattr(status, "local_height", None)
        if type(height) is not int or height <= 0:
            raise AllEndpointsUnavailable("current chain height unavailable")
        lower = max(1, height - _TX_RECENT_BLOCK_WINDOW + 1)
        return f"tx.height>={lower}"

    async def transactions(self, limit=20, page=1):
        """Return recent transactions without scanning the full transaction index."""
        if type(limit) is not int or not 1 <= limit <= 20 or type(page) is not int or not 1 <= page <= 100:
            raise ValueError("invalid transaction page")

        def normalized(endpoint: str, payload: object):
            try:
                rows, total = normalize_transactions(payload, limit)
                candidate = {"state": "available", "transactions": rows, "page": page,
                             "page_size": limit, "total": total,
                             "has_older": page < 100 and total is not None and page * limit < total,
                             "has_newer": page > 1, "source_host": self.adapter._host(endpoint)}
                return TypeAdapter(CosmosTransactionsResponse).validate_python(candidate).model_dump()
            except (MalformedUpstreamResponse, ValidationError):
                return None

        expression = await self._recent_transaction_expression()
        candidates = await self._operation_candidates("rest", "tx_search")
        first_empty = None
        empty_endpoints: list[str] = []
        indexing_unavailable = False
        for candidate in candidates:
            try:
                payload, _mode = await self._tx_search_payload(candidate, expression, page, limit)
            except Exception:
                continue
            response = normalized(candidate.endpoint, payload)
            if response is not None:
                if response["transactions"]:
                    for endpoint in empty_endpoints:
                        self._mark_operation_suspect("tx_search", endpoint)
                    self._clear_operation_suspect("tx_search", candidate.endpoint)
                    return response
                if first_empty is None:
                    first_empty = response
                empty_endpoints.append(candidate.endpoint)
                continue
            if _index_unavailable(payload):
                indexing_unavailable = True
                self._mark_operation_suspect("tx_search", candidate.endpoint)

        if first_empty is not None:
            return first_empty
        if indexing_unavailable:
            return {"state": "indexing_unavailable", "transactions": [], "page": page,
                    "page_size": limit, "total": None, "has_older": False, "has_newer": page > 1}
        raise AllEndpointsUnavailable("no valid transaction search response")

    async def transaction_lookup(self, tx_hash: str):
        """Resolve an exact hash without trusting one endpoint's false negative."""
        import re

        if not isinstance(tx_hash, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", tx_hash) is None:
            raise ValueError("invalid transaction hash")
        normalized_hash = tx_hash.upper()
        candidates = await self._operation_candidates("rpc", "tx_lookup")
        not_found_endpoints: list[str] = []
        for candidate in candidates:
            try:
                payload = await self.transport.get_object(
                    candidate.endpoint, f"/tx?hash=0x{normalized_hash}&prove=false",
                    accept_error_payload=True)
                error = payload.get("error")
                if isinstance(error, dict):
                    text = str(error.get("data") or error.get("message") or "")
                    if "not found" in text.lower():
                        not_found_endpoints.append(candidate.endpoint)
                    elif _index_unavailable({"message": text}):
                        self._mark_operation_suspect("tx_lookup", candidate.endpoint)
                    continue
                result = _mapping(payload.get("result"), "transaction lookup result")
                result_hash = _text(result.get("hash"), "transaction hash", 64).upper()
                if result_hash != normalized_hash or re.fullmatch(r"[0-9A-F]{64}", result_hash) is None:
                    raise MalformedUpstreamResponse("transaction hash mismatch")
                height = _integer(result.get("height"), "transaction height")
                index = _integer(result.get("index"), "transaction index")
                if height <= 0 or index > 10_000:
                    raise MalformedUpstreamResponse("invalid transaction location")
                for endpoint in not_found_endpoints:
                    self._mark_operation_suspect("tx_lookup", endpoint)
                self._clear_operation_suspect("tx_lookup", candidate.endpoint)
                return {"height": height, "index": index, "tx_hash": result_hash}
            except Exception:
                continue
        if not_found_endpoints:
            raise TransactionNotFound("transaction not found")
        raise AllEndpointsUnavailable("transaction lookup unavailable")

    async def _validator_event_search(self, expression: str, limit: int):
        """Prefer non-empty history while retaining a valid empty fallback."""
        cache_key = (self.definition.transport.network_id, "validator_event_search", (expression, limit))

        async def load():
            candidates = await self._operation_candidates("rest", "tx_search")
            first_empty = None
            empty_endpoints: list[str] = []
            for candidate in candidates:
                try:
                    payload, _mode = await self._tx_search_payload(candidate, expression, 1, limit)
                except Exception:
                    continue
                if _event_payload_valid(payload, limit):
                    if payload["txs"]:
                        for endpoint in empty_endpoints:
                            self._mark_operation_suspect("tx_search", endpoint)
                        self._clear_operation_suspect("tx_search", candidate.endpoint)
                        return payload
                    if first_empty is None:
                        first_empty = payload
                    empty_endpoints.append(candidate.endpoint)
                    continue
                if _index_unavailable(payload):
                    self._mark_operation_suspect("tx_search", candidate.endpoint)
            if first_empty is not None:
                return first_empty
            raise AllEndpointsUnavailable("validator event search unavailable")

        return await self.cache.get_or_load(cache_key, SECTION_TTL, load)
