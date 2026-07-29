"""Live account retrieval using the shared RPC freshness selector."""

import logging
from urllib.parse import urlsplit, urlunsplit

from api.account_adapters import AccountParseError, parse_auth_account, parse_coins
from api.network_profile import topaz_profile
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_candidates
from scripts.inspect_rpc import RpcError

LOGGER = logging.getLogger(__name__)


class AccountUnavailableError(RuntimeError):
    """No fresh RPC candidate returned consistent account data."""


def public_rpc_url(value: str) -> str:
    """Return a bounded credential- and parameter-free public HTTP RPC URL."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(char) < 33 for char in value):
        raise AccountParseError("invalid RPC URL")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        port = parsed.port
    except ValueError as exc:
        raise AccountParseError("invalid RPC URL") from exc
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{hostname}:{port}" if port is not None else hostname
    result = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    if len(result) > 2048:
        raise AccountParseError("invalid RPC URL")
    return result


def fetch_live_account(address: str, config) -> dict:
    profile = topaz_profile(config.chain_id)
    try:
        probes = probe_rpc_endpoints(
            list(config.rpc_urls), config.chain_id, config.rpc_max_height_lag,
            timeout=config.account_rpc_timeout_seconds,
        )
        candidates = suitable_rpc_candidates(probes)
    except Exception:
        LOGGER.warning("Account RPC discovery failed")
        raise AccountUnavailableError from None
    for candidate in candidates:
        try:
            auth_text = candidate.client.abci_query(f"auth/accounts/{address}", "")
            bank_text = candidate.client.abci_query(f"bank/balances/{address}", "")
            account = parse_auth_account(auth_text, address)
            balances = parse_coins(bank_text, profile)
            if account is None:
                if bank_text != "" or balances:
                    raise AccountParseError("inconsistent missing account")
                account = {"account_number": None, "sequence": None, "public_key": None}
            return {
                "address": address, "found": account["account_number"] is not None,
                "balances": balances, **account,
                "source": {"kind": "rpc", "chain_id": config.chain_id,
                           "rpc_url": public_rpc_url(candidate.client.base_url)},
                "observed_height": candidate.latest_height,
            }
        except (RpcError, AccountParseError, TypeError, ValueError):
            LOGGER.warning("Fresh RPC candidate returned unusable account data")
    raise AccountUnavailableError
