import base64
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from indexer.valopers_source import (
    MAX_DECODED_RESPONSE_BYTES,
    MAX_ENCODED_RESPONSE_CHARS,
    MAX_PREVIEW_CHARS,
    VALOPERS_RENDER_PREFIX,
    bounded_preview,
    build_detail_render_data,
    build_page_render_data,
    build_qrender_params,
    build_root_render_data,
    decode_qrender_response,
    fetch_render,
)
from scripts import probe_valopers
from scripts.inspect_rpc import RpcError

OPERATOR_ADDRESS = "g1" + "x" * 38


def response(value=b"rendered output", height=123):
    return {
        "result": {
            "response": {
                "height": str(height),
                "value": base64.b64encode(value).decode("ascii"),
            }
        }
    }


class FakeClient:
    def __init__(self, payload=None):
        self.payload = payload or response()
        self.calls = []

    def get(self, method, **params):
        self.calls.append((method, params))
        return self.payload


class RenderConstructionTests(unittest.TestCase):
    def test_root_render_string(self):
        self.assertEqual(build_root_render_data(), "gno.land/r/gnops/valopers:")

    def test_page_render_string(self):
        self.assertEqual(
            build_page_render_data("?page=2"), "gno.land/r/gnops/valopers:?page=2"
        )

    def test_operator_detail_render_string(self):
        self.assertEqual(
            build_detail_render_data(OPERATOR_ADDRESS),
            f"gno.land/r/gnops/valopers:{OPERATOR_ADDRESS}",
        )

    def test_invalid_page_and_operator_are_rejected(self):
        for value in ("page=2", "?page=0", "?page=2&extra=true", "?page=1000001"):
            with self.subTest(value=value), self.assertRaises(RpcError):
                build_page_render_data(value)
        for value in ("g1short", "G1" + "x" * 38, "g1" + "1" * 38):
            with self.subTest(value=value), self.assertRaises(RpcError):
                build_detail_render_data(value)

    def test_qrender_transport_uses_json_wrapped_base64(self):
        params = build_qrender_params(build_root_render_data(), 123)
        expected_base64 = "Z25vLmxhbmQvci9nbm9wcy92YWxvcGVyczo="
        self.assertEqual(params["path"], json.dumps("vm/qrender"))
        self.assertEqual(params["data"], json.dumps(expected_base64))
        self.assertEqual(base64.b64decode(json.loads(params["data"])), VALOPERS_RENDER_PREFIX.encode())
        self.assertNotIn("gno.land/", params["data"])
        self.assertEqual(params["height"], 123)
        self.assertEqual(params["prove"], "false")

    def test_each_fetch_uses_supplied_pinned_height_and_prove_false(self):
        client = FakeClient()
        for kind, render_data in (
            ("root", build_root_render_data()),
            ("page", build_page_render_data("?page=2")),
            ("detail", build_detail_render_data(OPERATOR_ADDRESS)),
        ):
            fetch_render(client, render_data, kind, 123)
        self.assertEqual(len(client.calls), 3)
        for method, params in client.calls:
            self.assertEqual(method, "abci_query")
            self.assertEqual(params["height"], 123)
            self.assertEqual(params["prove"], "false")


class ResponseDecodingTests(unittest.TestCase):
    def test_valid_response_is_decoded_and_summarized(self):
        result = decode_qrender_response(response(b"hello\nworld", 123), "root", 123)
        self.assertEqual(result.query_kind, "root")
        self.assertEqual(result.source_height, 123)
        self.assertEqual(result.response_height, 123)
        self.assertEqual(result.decoded_byte_count, 11)
        self.assertEqual(
            result.sha256, "26c60a61d01db5836ca70fefd44a6a016620413c8ef5f259a6c5612d4f79d3b8"
        )
        self.assertEqual(result.preview, r"hello\nworld")

    def test_response_height_must_be_exact(self):
        with self.assertRaisesRegex(RpcError, "height mismatch"):
            decode_qrender_response(response(height=122), "root", 123)
        for height in (None, "bad", "0123", True, 0):
            with self.subTest(height=height), self.assertRaisesRegex(RpcError, "invalid.*height"):
                decode_qrender_response(response(height=height), "root", 123)

    def test_invalid_response_base64_is_rejected(self):
        payload = response()
        payload["result"]["response"]["value"] = "not base64!"
        with self.assertRaisesRegex(RpcError, "invalid base64"):
            decode_qrender_response(payload, "root", 123)

    def test_invalid_decoded_utf8_is_rejected(self):
        with self.assertRaisesRegex(RpcError, "not UTF-8"):
            decode_qrender_response(response(b"\xff"), "root", 123)

    def test_missing_response_fields_are_rejected(self):
        payloads = ({}, {"result": {}}, {"result": {"response": {"height": "123"}}})
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaisesRegex(
                RpcError, "missing result.response.value"
            ):
                decode_qrender_response(payload, "root", 123)

    def test_encoded_response_limit_is_enforced_before_decode(self):
        payload = response()
        payload["result"]["response"]["value"] = "A" * (MAX_ENCODED_RESPONSE_CHARS + 1)
        with self.assertRaisesRegex(RpcError, "encoded response size limit"):
            decode_qrender_response(payload, "root", 123)

    def test_decoded_response_limit_is_enforced(self):
        with self.assertRaisesRegex(RpcError, "decoded response size limit"):
            decode_qrender_response(
                response(b"x" * (MAX_DECODED_RESPONSE_BYTES + 1)), "root", 123
            )

    def test_preview_is_bounded_and_sanitized(self):
        preview = bounded_preview("line1\nline2\r\t\x00" + "x" * 500)
        self.assertLessEqual(len(preview), MAX_PREVIEW_CHARS)
        self.assertNotIn("\n", preview)
        self.assertNotIn("\r", preview)
        self.assertNotIn("\t", preview)
        self.assertNotIn("\x00", preview)
        self.assertIn(r"\n", preview)
        self.assertIn(r"\u0000", preview)


class ProbeCliTests(unittest.TestCase):
    status_payload = {
        "result": {
            "node_info": {"network": "test-13"},
            "sync_info": {"latest_block_height": "123", "catching_up": False},
        }
    }

    def run_main(self, argv, client=None):
        client = client or FakeClient()
        stdout = StringIO()
        stderr = StringIO()
        with patch("scripts.probe_valopers.configured_rpc_urls", return_value=["http://rpc"]), patch(
            "scripts.probe_valopers.configured_chain_id", return_value="test-13"
        ), patch(
            "scripts.probe_valopers.select_healthy_rpc",
            return_value=(client, self.status_payload),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            code = probe_valopers.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), client

    def test_cli_defaults_to_root_only(self):
        code, output, errors, client = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(len(client.calls), 1)
        self.assertIn("kind=root source_height=123 response_height=123", output)

    def test_cli_supports_explicit_page_and_detail_at_one_height(self):
        code, output, _, client = self.run_main(
            ["--page-query", "?page=2", "--operator-address", OPERATOR_ADDRESS]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(client.calls), 3)
        self.assertIn("kind=root", output)
        self.assertIn("kind=page", output)
        self.assertIn("kind=detail", output)
        self.assertTrue(all(call[1]["height"] == 123 for call in client.calls))

    def test_cli_failure_is_nonzero_and_does_not_dump_payload(self):
        secret = "complete-render-body-secret"
        client = FakeClient(response(secret.encode(), height=122))
        code, output, errors, _ = self.run_main([], client)
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("Valopers probe failed: Qrender response height mismatch", errors)
        self.assertNotIn(secret, errors)

    def test_cli_rejects_unsafe_argument_before_rpc_selection(self):
        code, output, errors, client = self.run_main(["--page-query", "?page=2&crawl=true"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("Page query must have the form", errors)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
