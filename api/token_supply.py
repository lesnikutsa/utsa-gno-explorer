"""Bounded runtime TotalSupply lookup for source-verified GRC20 Realms."""

from collections import OrderedDict
from dataclasses import dataclass
import re
from threading import Lock
import time

from scripts.inspect_rpc import GnoRpcClient

TOKEN_SUPPLY_RPC_TIMEOUT_SECONDS = 3
TOKEN_SUPPLY_CACHE_TTL_SECONDS = 300
TOKEN_SUPPLY_CACHE_MAX_ENTRIES = 512
_QRESULT_RE = re.compile(r"^\(?([0-9]+)(?:\s+(?:u?int(?:8|16|32|64)?|big\.Int))?\)?$")


@dataclass(frozen=True)
class CachedSupply:
    stored_at: float
    raw_total_supply: str


class TokenSupplyCache:
    """Small process-local LRU cache; unsuccessful lookups are never inserted."""

    def __init__(self, *, ttl_seconds: float = TOKEN_SUPPLY_CACHE_TTL_SECONDS,
                 max_entries: int = TOKEN_SUPPLY_CACHE_MAX_ENTRIES) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._items: OrderedDict[tuple[str, str], CachedSupply] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple[str, str]) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if now - item.stored_at >= self.ttl_seconds:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return item.raw_total_supply

    def put(self, key: tuple[str, str], raw_total_supply: str) -> None:
        with self._lock:
            self._items[key] = CachedSupply(time.monotonic(), raw_total_supply)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


token_supply_cache = TokenSupplyCache()
NATIVE_GNOT_DENOM = "ugnot"
NATIVE_GNOT_DECIMALS = 6


def parse_total_supply(value: object) -> str | None:
    """Accept only a non-negative integer returned as one qeval scalar."""
    if not isinstance(value, str) or value != value.strip() or len(value) > 512:
        return None
    match = _QRESULT_RE.fullmatch(value)
    return match.group(1) if match else None


def decimal_amount(raw_total_supply: str, decimals: int) -> str:
    """Place a decimal point using string arithmetic without float conversion."""
    digits = raw_total_supply.lstrip("0") or "0"
    if decimals == 0:
        return digits
    digits = digits.zfill(decimals + 1)
    whole, fraction = digits[:-decimals], digits[-decimals:].rstrip("0")
    return whole if not fraction else f"{whole}.{fraction}"


def query_total_supply(*, rpc_url: str, path: str) -> str | None:
    """Execute the sole runtime expression supported by the token supply API."""
    expression = f"{path}.TotalSupply()"
    with GnoRpcClient(rpc_url, timeout=TOKEN_SUPPLY_RPC_TIMEOUT_SECONDS) as client:
        return parse_total_supply(client.abci_query("vm/qeval", expression))


def query_native_gnot_supply(*, rpc_url: str) -> str | None:
    """Query only the fixed native GNOT bank supply path."""
    with GnoRpcClient(rpc_url, timeout=TOKEN_SUPPLY_RPC_TIMEOUT_SECONDS) as client:
        return parse_total_supply(client.abci_query(f"bank/supply/{NATIVE_GNOT_DENOM}", ""))
