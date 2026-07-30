import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scripts.inspect_rpc as inspect_rpc
from scripts.inspect_rpc import (
    GnoRpcClient,
    RpcError,
    build_summary,
    configured_max_height_lag,
    configured_rpc_urls,
    fetch_summary,
    parse_block,
    parse_commit,
    parse_status,
    parse_validators,
    select_healthy_rpc,
    signature_signed,
    signer_address,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    def __init__(self, base_url, responses=None, error=None, delay=0):
        self.base_url = base_url.rstrip("/") + "/"
        self.responses = responses or {}
        self.error = error
        self.delay = delay
        self.calls = []

    def get(self, method, **params):
        self.calls.append((method, params))
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.responses[method]


class FakeResponse:
    def __init__(self, payload=None, error=None, json_error=None):
        self.payload = payload if payload is not None else {"result": {}}
        self.error = error
        self.json_error = json_error
        self.closed = False

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload

    def close(self):
        self.closed = True


class FakeCookies:
    def __init__(self):
        self.clear_count = 0

    def clear(self):
        self.clear_count += 1


def fake_requests(session_factory):
    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    class HTTPAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    return types.SimpleNamespace(
        Session=session_factory,
        Timeout=Timeout,
        RequestException=RequestException,
        adapters=types.SimpleNamespace(HTTPAdapter=HTTPAdapter),
    )


class RpcSessionPoolTests(unittest.TestCase):
    def test_requests_import_error_uses_unchanged_urllib_transport(self):
        response = Mock()
        response.read.return_value = b'{"result":{"height":"1"}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        real_import = __import__

        def import_without_requests(name, *args, **kwargs):
            if name == "requests":
                raise ImportError
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_requests), patch(
            "scripts.inspect_rpc.urlopen", return_value=response
        ) as urlopen:
            payload = GnoRpcClient("https://rpc.example", timeout=7).get("status", height=3)

        self.assertEqual(payload["result"]["height"], "1")
        urlopen.assert_called_once_with("https://rpc.example/status?height=3", timeout=7)

    def test_urllib_transport_rejects_request_after_close_without_network_io(self):
        client = GnoRpcClient("https://rpc.example")
        client.close()
        client.close()
        real_import = __import__
        sessions = []

        class Session:
            def __init__(self):
                sessions.append(self)

        def import_without_requests(name, *args, **kwargs):
            if name == "requests":
                raise AssertionError("requests import attempted")
            return real_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"requests": fake_requests(Session)}), patch.object(
            inspect_rpc, "urlopen"
        ) as urlopen:
            with patch(
                "builtins.__import__", side_effect=import_without_requests
            ) as import_mock:
                with self.assertRaisesRegex(RpcError, "RPC client is closed"):
                    client.get("status")

        urlopen.assert_not_called()
        import_mock.assert_not_called()
        self.assertEqual(sessions, [])

    def test_urllib_transport_rejects_request_after_context_manager_exit(self):
        with GnoRpcClient("https://rpc.example") as client:
            pass
        real_import = __import__
        sessions = []

        class Session:
            def __init__(self):
                sessions.append(self)

        def import_without_requests(name, *args, **kwargs):
            if name == "requests":
                raise AssertionError("requests import attempted")
            return real_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"requests": fake_requests(Session)}), patch.object(
            inspect_rpc, "urlopen"
        ) as urlopen:
            with patch(
                "builtins.__import__", side_effect=import_without_requests
            ) as import_mock:
                with self.assertRaisesRegex(RpcError, "RPC client is closed"):
                    client.get("status")

        urlopen.assert_not_called()
        import_mock.assert_not_called()
        self.assertEqual(sessions, [])

    def test_sequential_calls_reuse_one_configured_session(self):
        sessions = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()
                self.mounts = []
                self.responses = []
                self.closed = False
                sessions.append(self)

            def mount(self, prefix, adapter):
                self.mounts.append((prefix, adapter))

            def get(self, *args, **kwargs):
                response = FakeResponse()
                self.responses.append(response)
                return response

            def close(self):
                self.closed = True

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            client = GnoRpcClient("https://rpc.example")
            client.get("status")
            client.get("status")

        self.assertEqual(len(sessions), 1)
        self.assertEqual([prefix for prefix, _ in sessions[0].mounts], ["http://", "https://"])
        for _, adapter in sessions[0].mounts:
            self.assertEqual(adapter.kwargs["max_retries"], 0)
            self.assertTrue(adapter.kwargs["pool_block"])
        self.assertTrue(all(response.closed for response in sessions[0].responses))
        self.assertEqual(sessions[0].cookies.clear_count, 2)

    def test_concurrent_calls_have_exclusive_sessions_and_overlap(self):
        barrier = threading.Barrier(2)
        sessions = []
        active = set()
        active_lock = threading.Lock()

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()
                sessions.append(self)

            def mount(self, *args):
                pass

            def get(self, *args, **kwargs):
                with active_lock:
                    self.assert_not_active = self not in active
                    active.add(self)
                barrier.wait(timeout=2)
                with active_lock:
                    active.remove(self)
                return FakeResponse()

            def close(self):
                pass

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            client = GnoRpcClient("https://rpc.example")
            errors = []

            def request(method):
                try:
                    client.get(method)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=request, args=(method,)) for method in ("auth", "bank")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertFalse(errors)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.assert_not_active for session in sessions))
        self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_pool_exhaustion_is_bounded_and_returned_session_is_reused(self):
        release = threading.Event()
        entered = threading.Event()
        sessions = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()
                sessions.append(self)

            def mount(self, *args):
                pass

            def get(self, method, **kwargs):
                if method.endswith("hold"):
                    entered.set()
                    release.wait(timeout=2)
                return FakeResponse()

            def close(self):
                pass

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}), patch(
            "scripts.inspect_rpc._SESSION_POOL_MAX_SIZE", 1
        ):
            client = GnoRpcClient("https://rpc.example", timeout=0.02)
            holder = threading.Thread(target=client.get, args=("hold",))
            holder.start()
            self.assertTrue(entered.wait(timeout=1))
            with self.assertRaisesRegex(RpcError, "session pool exhausted"):
                client.get("blocked")
            release.set()
            holder.join(timeout=2)
            client.get("reused")

        self.assertFalse(holder.is_alive())
        self.assertEqual(len(sessions), 1)

    def test_failures_return_session_and_close_response(self):
        responses = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()

            def mount(self, *args):
                pass

            def get(self, *args, **kwargs):
                response = FakeResponse(error=requests.Timeout("slow"))
                responses.append(response)
                return response

            def close(self):
                pass

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            client = GnoRpcClient("https://rpc.example")
            with self.assertRaisesRegex(RpcError, "timed out"):
                client.get("status")
        self.assertTrue(responses[0].closed)
        self.assertEqual(client._idle_sessions.qsize(), 1)

    def test_request_invalid_json_and_http_429_are_not_retried(self):
        responses = []
        requested = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()

            def mount(self, *args):
                pass

            def get(self, url, **kwargs):
                requested.append(url)
                return responses.pop(0)

            def close(self):
                pass

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            client = GnoRpcClient("https://rpc.example")
            responses.append(FakeResponse(error=requests.RequestException("failed")))
            with self.assertRaisesRegex(RpcError, "request failed"):
                client.get("request-error")
            responses.append(FakeResponse(json_error=json.JSONDecodeError("bad", "", 0)))
            with self.assertRaisesRegex(RpcError, "not valid JSON"):
                client.get("invalid-json")
            responses.append(FakeResponse(error=requests.RequestException("429 Too Many Requests")))
            with self.assertRaisesRegex(RpcError, "429 Too Many Requests"):
                client.get("limited")

        self.assertEqual(len(requested), 3)
        self.assertEqual(client._idle_sessions.qsize(), 1)

    def test_close_and_context_manager_lifecycle(self):
        sessions = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()
                self.closed = False
                sessions.append(self)

            def mount(self, *args):
                pass

            def get(self, *args, **kwargs):
                return FakeResponse()

            def close(self):
                self.closed = True

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            with GnoRpcClient("https://rpc.example") as client:
                client.get("status")
            client.close()
            self.assertTrue(sessions[0].closed)
            with self.assertRaisesRegex(RpcError, "client is closed"):
                client.get("status")
        self.assertEqual(len(sessions), 1)

    def test_close_racing_with_session_checkout_cannot_create_session(self):
        checked_open = threading.Event()
        continue_checkout = threading.Event()
        sessions = []

        class Session:
            def __init__(self):
                sessions.append(self)

        requests = fake_requests(Session)
        client = GnoRpcClient("https://rpc.example")
        original_check_open = client._check_open

        def pause_after_open_check():
            original_check_open()
            checked_open.set()
            continue_checkout.wait(timeout=2)

        client._check_open = pause_after_open_check
        errors = []

        with patch.dict(sys.modules, {"requests": requests}):
            request = threading.Thread(
                target=lambda: errors.append(self._captured_rpc_error(client))
            )
            request.start()
            self.assertTrue(checked_open.wait(timeout=1))
            client.close()
            continue_checkout.set()
            request.join(timeout=2)

        self.assertFalse(request.is_alive())
        self.assertEqual(len(sessions), 0)
        self.assertEqual(str(errors[0]), "RPC client is closed")

    @staticmethod
    def _captured_rpc_error(client):
        try:
            client.get("status")
        except RpcError as exc:
            return exc
        raise AssertionError("request unexpectedly succeeded")

    def test_checked_out_session_closes_when_returned_after_close(self):
        entered = threading.Event()
        release = threading.Event()
        sessions = []

        class Session:
            def __init__(self):
                self.cookies = FakeCookies()
                self.closed = False
                sessions.append(self)

            def mount(self, *args):
                pass

            def get(self, *args, **kwargs):
                entered.set()
                release.wait(timeout=2)
                return FakeResponse()

            def close(self):
                self.closed = True

        requests = fake_requests(Session)
        with patch.dict(sys.modules, {"requests": requests}):
            client = GnoRpcClient("https://rpc.example")
            request = threading.Thread(target=client.get, args=("status",))
            request.start()
            self.assertTrue(entered.wait(timeout=1))
            client.close()
            self.assertFalse(sessions[0].closed)
            release.set()
            request.join(timeout=2)

        self.assertFalse(request.is_alive())
        self.assertTrue(sessions[0].closed)


class InspectRpcParsingTests(unittest.TestCase):
    def test_parse_status_extracts_chain_height_version_and_sync(self):
        parsed = parse_status(load("status.json"))
        self.assertEqual(parsed["chain_id"], "test-13")
        self.assertEqual(parsed["latest_height"], 123)
        self.assertEqual(parsed["node_version"], "tm2-build-version")
        self.assertFalse(parsed["catching_up"])

    def test_status_prefers_build_version_but_falls_back_to_node_info_version(self):
        status = load("status.json")
        status["result"].pop("build_version")
        self.assertEqual(parse_status(status)["node_version"], "node-fallback-version")

    def test_validators_response_requires_block_height(self):
        validators = load("validators.json")
        validators["result"].pop("block_height")
        with self.assertRaisesRegex(RpcError, "missing result.block_height"):
            parse_validators(validators)

    def test_commit_height_is_derived_from_signed_header_header_height(self):
        commit = load("commit.json")
        commit["result"]["signed_header"]["commit"]["height"] = "999"
        self.assertEqual(parse_commit(commit)["height"], 122)

    def test_commit_canonical_must_be_boolean(self):
        commit = load("commit.json")
        commit["result"]["canonical"] = {"height": "122"}
        with self.assertRaisesRegex(RpcError, "canonical must be a boolean"):
            parse_commit(commit)

    def test_parse_block_does_not_treat_last_commit_as_commit_for_block_height(self):
        parsed = parse_block(load("block.json"))
        self.assertNotIn("commit_signatures", parsed)
        self.assertEqual(parsed["height"], 123)
        self.assertEqual(parsed["tx_count"], 2)
        self.assertEqual(parsed["hash_base64"], "AQIDBA==")
        self.assertEqual(parsed["hash_hex"], "01020304")
        self.assertTrue(parsed["transactions"][0]["base64_decoded"])
        self.assertEqual(parsed["transactions"][0]["decoded_size_bytes"], 5)

    def test_block_hash_requires_valid_base64(self):
        block = load("block.json")
        block["result"]["block_meta"]["block_id"]["hash"] = "not base64!!!"
        with self.assertRaisesRegex(RpcError, "invalid base64"):
            parse_block(block)

    def test_block_hash_is_required(self):
        block = load("block.json")
        del block["result"]["block_meta"]["block_id"]["hash"]
        with self.assertRaisesRegex(RpcError, "missing result.block_meta.block_id.hash"):
            parse_block(block)

    def test_malformed_transaction_base64_is_marked_not_decoded(self):
        block = load("block.json")
        block["result"]["block"]["data"]["txs"] = ["not base64!!!"]
        block["result"]["block"]["header"]["num_txs"] = "1"
        tx = parse_block(block)["transactions"][0]
        self.assertEqual(tx["raw_base64"], "not base64!!!")
        self.assertEqual(tx["encoded_size_chars"], 13)
        self.assertFalse(tx["base64_decoded"])
        self.assertEqual(tx["decoded_size_bytes"], 0)

    def test_block_num_txs_must_match_data_txs_length(self):
        block = load("block.json")
        block["result"]["block"]["header"]["num_txs"] = "3"
        with self.assertRaisesRegex(RpcError, "transaction count mismatch"):
            parse_block(block)

    def test_parse_commit_reads_real_tm2_shape_and_canonical(self):
        parsed = parse_commit(load("commit.json"))
        self.assertEqual(parsed["height"], 122)
        self.assertEqual(parsed["header_height"], 122)
        self.assertIs(parsed["canonical"], True)
        self.assertEqual(len(parsed["precommits"]), 3)

    def test_parse_validators_extracts_block_height_addresses_and_power(self):
        validators = parse_validators(load("validators.json"))
        self.assertEqual(validators["block_height"], 122)
        self.assertEqual(validators["validators"][0]["address"], "VAL1")
        self.assertEqual(validators["validators"][0]["pub_key_type"], "/tm.PubKeyEd25519")
        self.assertEqual(validators["validators"][0]["pub_key_display_type"], "Ed25519")
        self.assertEqual(validators["validators"][1]["voting_power"], 20)

    def test_null_precommit_helpers_are_safe(self):
        self.assertIsNone(signer_address(None))
        self.assertIsNone(signer_address("bad"))
        self.assertFalse(signature_signed(None))
        self.assertFalse(signature_signed("bad"))

    def test_build_summary_uses_h_minus_one_and_handles_signed_and_missed(self):
        summary = build_summary("http://rpc", load("status.json"), load("block.json"), load("commit.json"), load("validators.json"))
        self.assertEqual(summary.latest_height, 123)
        self.assertEqual(summary.signing_height, 122)
        self.assertEqual(summary.commit_height, 122)
        self.assertEqual(summary.validators_height, 122)
        self.assertEqual([v["address"] for v in summary.signed_validators], ["VAL1"])
        self.assertEqual([v["address"] for v in summary.missed_validators], ["VAL2", "VAL3"])

    def test_height_mismatch_between_commit_and_validators_fails(self):
        validators = load("validators.json")
        validators["result"]["block_height"] = "121"
        with self.assertRaisesRegex(RpcError, "Validator-set height mismatch"):
            build_summary("http://rpc", load("status.json"), load("block.json"), load("commit.json"), validators)

    def test_malformed_commit_response_fails_clearly(self):
        with self.assertRaisesRegex(RpcError, "Malformed commit response"):
            parse_commit({"result": {"signed_header": {"header": {"height": "122"}}}})

    def test_fetch_summary_requests_block_h_commit_h_minus_one_and_validators_h_minus_one(self):
        client = FakeClient("http://rpc", {"block": load("block.json"), "commit": load("commit.json"), "validators": load("validators.json")})
        summary = fetch_summary(client, load("status.json"))
        self.assertEqual(summary.signing_height, 122)
        self.assertEqual(client.calls[0], ("block", {"height": 123}))
        self.assertEqual(client.calls[1], ("commit", {"height": 122}))
        self.assertEqual(client.calls[2], ("validators", {"height": 122}))


class RpcSelectionTests(unittest.TestCase):
    def test_delegates_to_shared_selector_and_preserves_return_contract(self):
        client = FakeClient("http://selected")
        payload = load("status.json")
        selected = Mock(client=client, status_payload=payload)
        with patch("indexer.rpc.select_rpc", return_value=selected) as shared:
            result = select_healthy_rpc(
                ["http://one", "http://two"], timeout=7,
                expected_chain_id="test-13", max_height_lag=4,
            )
        shared.assert_called_once_with(["http://one", "http://two"], "test-13", 4, 7)
        self.assertEqual(result, (client, payload))

    def test_one_failed_rpc_followed_by_working_fallback(self):
        clients = [FakeClient("http://bad", error=RpcError("down")), FakeClient("http://good", {"status": load("status.json")})]
        by_url = {"http://bad": clients[0], "http://good": clients[1]}
        with patch("indexer.rpc.GnoRpcClient", side_effect=lambda url, timeout: by_url[url]):
            selected, status = select_healthy_rpc(["http://bad", "http://good"], expected_chain_id="test-13", max_height_lag=10)
        self.assertIs(selected, clients[1])
        self.assertEqual(parse_status(status)["latest_height"], 123)

    def test_second_equally_fresh_rpc_is_selected_when_faster(self):
        payload = load("status.json")
        clients = {
            "http://slow": FakeClient("http://slow", {"status": payload}, delay=0.08),
            "http://fast": FakeClient("http://fast", {"status": payload}),
        }
        with patch("indexer.rpc.GnoRpcClient", side_effect=lambda url, timeout: clients[url]):
            selected, status = select_healthy_rpc(
                ["http://slow", "http://fast"], expected_chain_id="test-13", max_height_lag=10,
            )
        self.assertIs(selected, clients["http://fast"])
        self.assertIs(status, payload)

    def test_faster_wrong_chain_catching_up_and_stale_endpoints_are_rejected(self):
        for rejection in ("wrong_chain", "catching_up", "stale"):
            with self.subTest(rejection=rejection):
                rejected = load("status.json")
                healthy = load("status.json")
                healthy["result"]["sync_info"]["latest_block_height"] = "120"
                if rejection == "wrong_chain":
                    rejected["result"]["node_info"]["network"] = "wrong-chain"
                    rejected["result"]["sync_info"]["latest_block_height"] = "120"
                elif rejection == "catching_up":
                    rejected["result"]["sync_info"]["catching_up"] = True
                    rejected["result"]["sync_info"]["latest_block_height"] = "120"
                else:
                    rejected["result"]["sync_info"]["latest_block_height"] = "100"
                clients = {
                    "http://rejected": FakeClient("http://rejected", {"status": rejected}),
                    "http://healthy": FakeClient("http://healthy", {"status": healthy}, delay=0.08),
                }
                with patch("indexer.rpc.GnoRpcClient", side_effect=lambda url, timeout: clients[url]):
                    selected, status = select_healthy_rpc(
                        ["http://rejected", "http://healthy"],
                        expected_chain_id="test-13", max_height_lag=5,
                    )
                self.assertIs(selected, clients["http://healthy"])
                self.assertIs(status, healthy)

    def test_all_rpc_endpoints_unavailable(self):
        with patch("indexer.rpc.GnoRpcClient", return_value=FakeClient("http://bad", error=RpcError("down"))):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://bad"], expected_chain_id="test-13", max_height_lag=10)

    def test_catching_up_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["sync_info"]["catching_up"] = True
        with patch("indexer.rpc.GnoRpcClient", return_value=FakeClient("http://syncing", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://syncing"], expected_chain_id="test-13", max_height_lag=10)

    def test_wrong_chain_id_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["node_info"]["network"] = "wrong-chain"
        with patch("indexer.rpc.GnoRpcClient", return_value=FakeClient("http://wrong", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected"):
                select_healthy_rpc(["http://wrong"], expected_chain_id="test-13", max_height_lag=10)

    def test_malformed_status_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["sync_info"].pop("latest_block_height")
        with patch("indexer.rpc.GnoRpcClient", return_value=FakeClient("http://bad-status", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected"):
                select_healthy_rpc(["http://bad-status"], expected_chain_id="test-13", max_height_lag=10)

    def test_first_endpoint_stale_second_endpoint_current_selected(self):
        stale = load("status.json")
        stale["result"]["sync_info"]["latest_block_height"] = "100"
        current = load("status.json")
        current["result"]["sync_info"]["latest_block_height"] = "120"
        clients = [FakeClient("http://stale", {"status": stale}), FakeClient("http://current", {"status": current})]
        by_url = {"http://stale": clients[0], "http://current": clients[1]}
        with patch("indexer.rpc.GnoRpcClient", side_effect=lambda url, timeout: by_url[url]):
            selected, status = select_healthy_rpc(["http://stale", "http://current"], expected_chain_id="test-13", max_height_lag=10)
        self.assertIs(selected, clients[1])
        self.assertEqual(parse_status(status)["latest_height"], 120)

    def test_all_endpoints_rejected_when_none_are_healthy(self):
        wrong_chain = load("status.json")
        wrong_chain["result"]["node_info"]["network"] = "wrong-chain"
        malformed = load("status.json")
        malformed["result"]["sync_info"].pop("latest_block_height")
        clients = [FakeClient("http://wrong", {"status": wrong_chain}), FakeClient("http://malformed", {"status": malformed})]
        by_url = {"http://wrong": clients[0], "http://malformed": clients[1]}
        with patch("indexer.rpc.GnoRpcClient", side_effect=lambda url, timeout: by_url[url]):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://wrong", "http://malformed"], expected_chain_id="test-13", max_height_lag=10)

    def test_configured_max_height_lag_from_env(self):
        with patch.dict(os.environ, {"RPC_MAX_HEIGHT_LAG": "7"}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                self.assertEqual(configured_max_height_lag(), 7)

    def test_legacy_gno_rpc_url_support(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"GNO_RPC_URL": "http://legacy"}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                self.assertEqual(configured_rpc_urls(), ["http://legacy"])

    def test_env_file_and_ordered_gno_rpc_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {}, clear=True):
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("GNO_RPC_URLS=http://one,http://two\n")
            with patch("scripts.inspect_rpc.Path", return_value=env_path):
                self.assertEqual(configured_rpc_urls(), ["http://one", "http://two"])

    def test_both_rpc_module_import_orders_are_safe(self):
        commands = (
            "import indexer.rpc; import scripts.inspect_rpc",
            "import scripts.inspect_rpc; import indexer.rpc",
        )
        for command in commands:
            with self.subTest(command=command):
                completed = subprocess.run(
                    [sys.executable, "-c", command], capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
