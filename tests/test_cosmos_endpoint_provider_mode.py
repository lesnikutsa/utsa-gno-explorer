import asyncio
from types import SimpleNamespace
from urllib.parse import urlsplit

import api.cosmos.service as service_module
from api.cosmos.cache import RequestCache
from api.cosmos.registry import (CANONICAL_NETWORKS, NETWORKS, get_network,
                                 provider_alias_id, public_networks)
from api.cosmos.service import CosmosService


def candidate(endpoint, height, latency):
    return SimpleNamespace(endpoint=endpoint, height=height, latency=latency)


def test_atomone_declares_three_ordered_rpc_api_pairs():
    definition = CANONICAL_NETWORKS["atomone-mainnet"]
    assert [provider.id for provider in definition.endpoint_providers] == [
        "utsa", "itrocket", "publicnode"]
    assert [provider.label for provider in definition.endpoint_providers] == [
        "UTSA", "IT Rocket", "PublicNode"]
    assert tuple(provider.rpc_endpoint for provider in definition.endpoint_providers) == definition.transport.rpc_endpoints
    assert tuple(provider.rest_endpoint for provider in definition.endpoint_providers) == definition.transport.rest_endpoints
    assert len(definition.endpoint_providers) == 3


def test_manual_provider_aliases_pin_exactly_one_pair_and_stay_private():
    canonical = CANONICAL_NETWORKS["atomone-mainnet"]
    for provider in canonical.endpoint_providers:
        alias_id = provider_alias_id("atomone-mainnet", provider.id)
        alias = get_network(alias_id)
        assert alias is NETWORKS[alias_id]
        assert alias.canonical_id == "atomone-mainnet"
        assert alias.selected_provider_id == provider.id
        assert alias.transport.rpc_endpoints == (provider.rpc_endpoint,)
        assert alias.transport.rest_endpoints == (provider.rest_endpoint,)
        assert len(alias.endpoint_providers) == 1

    public_ids = [item["id"] for item in public_networks()]
    assert "atomone-mainnet" in public_ids
    assert all("-provider-" not in network_id for network_id in public_ids)


def test_endpoint_status_reports_independent_auto_rpc_and_api_preferences():
    definition = CANONICAL_NETWORKS["atomone-mainnet"]
    providers = {provider.id: provider for provider in definition.endpoint_providers}
    service = object.__new__(CosmosService)
    service.definition = definition
    service.cache = RequestCache()

    rpc_candidates = (
        candidate(providers["publicnode"].rpc_endpoint, 10_000, 0.010),
        candidate(providers["utsa"].rpc_endpoint, 10_000, 0.020),
        candidate(providers["itrocket"].rpc_endpoint, 9_999, 0.030),
    )
    rest_candidates = (
        candidate(providers["itrocket"].rest_endpoint, 10_000, 0.015),
        candidate(providers["utsa"].rest_endpoint, 10_000, 0.025),
        candidate(providers["publicnode"].rest_endpoint, 10_000, 0.035),
    )

    async def cached(kind):
        return rpc_candidates if kind == "rpc" else rest_candidates

    service.adapter = SimpleNamespace(
        _cached_candidates=cached,
        _host=lambda endpoint: urlsplit(endpoint).hostname,
    )

    result = asyncio.run(service.endpoint_status())
    assert result["mode"] == "auto"
    assert result["selected_provider_id"] is None
    assert result["preferred_rpc_provider_id"] == "publicnode"
    assert result["preferred_api_provider_id"] == "itrocket"
    assert result["mixed_providers"] is True
    assert len(result["providers"]) == 3
    assert all(row["rpc"]["state"] == "healthy" for row in result["providers"])
    assert all(row["api"]["state"] == "healthy" for row in result["providers"])
    assert all(row["rpc"]["tx_index"] == "unknown" for row in result["providers"])
    assert all(row["rpc"]["lowest_available_height"] is None for row in result["providers"])


def test_endpoint_status_keeps_unavailable_side_visible():
    definition = CANONICAL_NETWORKS["atomone-mainnet"]
    providers = {provider.id: provider for provider in definition.endpoint_providers}
    service = object.__new__(CosmosService)
    service.definition = definition
    service.cache = RequestCache()

    async def cached(kind):
        if kind == "rpc":
            return (candidate(providers["utsa"].rpc_endpoint, 10_000, 0.010),)
        return (candidate(providers["itrocket"].rest_endpoint, 10_000, 0.020),)

    service.adapter = SimpleNamespace(
        _cached_candidates=cached,
        _host=lambda endpoint: urlsplit(endpoint).hostname,
    )

    result = asyncio.run(service.endpoint_status())
    rows = {row["id"]: row for row in result["providers"]}
    assert result["mixed_providers"] is True
    assert rows["utsa"]["rpc"]["state"] == "healthy"
    assert rows["utsa"]["api"]["state"] == "unavailable"
    assert rows["itrocket"]["rpc"]["state"] == "unavailable"
    assert rows["itrocket"]["api"]["state"] == "healthy"
    assert rows["publicnode"]["rpc"]["state"] == "unavailable"
    assert rows["publicnode"]["api"]["state"] == "unavailable"


def test_rpc_capabilities_refine_only_the_method_with_a_bad_reported_floor_and_share_cache(monkeypatch):
    monkeypatch.setattr(service_module, "_PROVIDER_HISTORY_PACING", 0.0)
    monkeypatch.setattr(service_module, "_PROVIDER_HISTORY_RETRY_DELAY", 0.0)

    definition = CANONICAL_NETWORKS["atomone-mainnet"]
    provider = definition.endpoint_providers[0]
    service = object.__new__(CosmosService)
    service.definition = definition
    service.cache = RequestCache()
    service.adapter = SimpleNamespace(_host=lambda endpoint: urlsplit(endpoint).hostname)

    calls = []
    transient_seen = False

    def block(height):
        return {"result": {"block": {"header": {"height": str(height)}}}}

    def commit(height):
        return {"result": {"signed_header": {
            "header": {"height": str(height)},
            "commit": {"height": str(height)},
        }}}

    def results(height):
        return {"result": {"height": str(height)}}

    class Transport:
        async def get_object(self, endpoint, path, **_kwargs):
            nonlocal transient_seen
            calls.append((endpoint, path))
            if path == "/status":
                return {
                    "result": {
                        "sync_info": {
                            "latest_block_height": "100",
                            "latest_block_time": "2026-09-06T00:00:00Z",
                            "catching_up": False,
                        },
                        "node_info": {
                            "network": "atomone-1",
                            "version": "0.38.22",
                            "other": {"tx_index": "on"},
                        },
                        "application_version": {
                            "name": "atomone",
                            "version": "4.1.0",
                            "cosmos_sdk_version": "v0.50.0",
                            "comet_version": "0.38.22",
                        },
                    }
                }

            kind = "block_results" if path.startswith("/block_results?") else (
                "commit" if path.startswith("/commit?") else "block")
            height = int(path.rsplit("=", 1)[1])

            if height == 1:
                return {"error": {"data": "height 1 is not available, lowest height is 20"}}
            if kind == "block":
                return block(height)
            if kind == "commit":
                return commit(height)
            if height == 59 and not transient_seen:
                transient_seen = True
                return {"code": 429, "message": "rate limit exceeded"}
            if height < 40:
                return {"error": {"data": f"could not find results for height #{height}"}}
            return results(height)

    service.transport = Transport()

    async def run():
        first = await service._provider_rpc_capabilities(provider, "atomone-mainnet")
        first_call_count = len(calls)
        second = await service._provider_rpc_capabilities(provider, "atomone-mainnet")
        return first, second, first_call_count

    first, second, first_call_count = asyncio.run(run())
    assert first == second == {
        "tx_index": "on",
        "lowest_available_height": 40,
    }
    assert transient_seen is True
    assert len(calls) == first_call_count
    assert calls.count((provider.rpc_endpoint, "/status")) == 1
    assert {(provider.rpc_endpoint, path) for path in (
        "/block?height=1", "/commit?height=1", "/block_results?height=1")}.issubset(set(calls))
    assert first_call_count <= 22
    assert all("tx_search" not in path and not path.startswith("/tx?") for _endpoint, path in calls)


def test_rpc_capabilities_do_not_turn_persistent_transient_errors_into_fake_history_floor(monkeypatch):
    monkeypatch.setattr(service_module, "_PROVIDER_HISTORY_PACING", 0.0)
    monkeypatch.setattr(service_module, "_PROVIDER_HISTORY_RETRY_DELAY", 0.0)

    definition = CANONICAL_NETWORKS["atomone-mainnet"]
    provider = definition.endpoint_providers[0]
    service = object.__new__(CosmosService)
    service.definition = definition
    service.cache = RequestCache()
    service.adapter = SimpleNamespace(_host=lambda endpoint: urlsplit(endpoint).hostname)

    def block(height):
        return {"result": {"block": {"header": {"height": str(height)}}}}

    def commit(height):
        return {"result": {"signed_header": {
            "header": {"height": str(height)},
            "commit": {"height": str(height)},
        }}}

    class Transport:
        async def get_object(self, _endpoint, path, **_kwargs):
            if path == "/status":
                return {
                    "result": {
                        "sync_info": {
                            "latest_block_height": "100",
                            "latest_block_time": "2026-09-06T00:00:00Z",
                            "catching_up": False,
                        },
                        "node_info": {
                            "network": "atomone-1",
                            "version": "0.38.22",
                            "other": {"tx_index": "on"},
                        },
                    }
                }
            height = int(path.rsplit("=", 1)[1])
            if height == 1:
                return {"error": {"data": "height 1 is not available, lowest height is 20"}}
            if path.startswith("/block?"):
                return block(height)
            if path.startswith("/commit?"):
                return commit(height)
            return {"code": 429, "message": "rate limit exceeded"}

    service.transport = Transport()
    result = asyncio.run(service._provider_rpc_capabilities(provider, "atomone-mainnet"))
    assert result == {"tx_index": "on", "lowest_available_height": None}
