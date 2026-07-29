"""Live account retrieval using the shared RPC freshness selector."""

import json
import logging

from api.account_adapters import AccountParseError, parse_auth_account, parse_coins
from api.network_profile import topaz_profile
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_candidates
from scripts.inspect_rpc import RpcError

LOGGER = logging.getLogger(__name__)


class AccountUnavailableError(RuntimeError):
    """No fresh RPC candidate returned consistent account data."""


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
            auth_text = candidate.client.abci_query(f"auth/accounts/{address}", json.dumps(address))
            bank_text = candidate.client.abci_query(f"bank/balances/{address}", json.dumps(address))
            account = parse_auth_account(auth_text, address)
            balances = parse_coins(bank_text, profile)
            if account is None:
                if bank_text != "" or balances:
                    raise AccountParseError("inconsistent missing account")
                account = {"account_number": None, "sequence": None, "public_key": None}
            return {
                "address": address, "found": account["account_number"] is not None,
                "balances": balances, **account,
                "source": {"kind": "rpc", "chain_id": config.chain_id, "rpc_url": candidate.client.base_url.rstrip("/")},
                "observed_height": candidate.latest_height,
            }
        except (RpcError, AccountParseError, TypeError, ValueError):
            LOGGER.warning("Fresh RPC candidate returned unusable account data")
    raise AccountUnavailableError
