import base64
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
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
REPO_ROOT = Path(__file__).resolve().parents[1]


def response(value=b"rendered output", height="0", error=None, log=""):
    return {
        "result": {
            "response": {
                "Height": height,
                "Key": None,
                "Proof": None,
                "ResponseBase": {
                    "Error": error,
                    "Data": base64.b64encode(value).decode("ascii"),
                    "Events": [],
                    "Log": log,
                    "Info": "",
                },
                "Value": None,
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
        result = decode_qrender_response(response(b"hello\nworld"), "root", 123)
        self.assertEqual(result.query_kind, "root")
        self.assertEqual(result.source_height, 123)
        self.assertIsNone(result.response_height)
        self.assertEqual(result.decoded_byte_count, 11)
        self.assertEqual(
            result.sha256, "26c60a61d01db5836ca70fefd44a6a016620413c8ef5f259a6c5612d4f79d3b8"
        )
        self.assertEqual(result.preview, r"hello\nworld")
        self.assertEqual(result.decoded_text, "hello\nworld")

    def test_decoded_text_is_hidden_from_repr(self):
        secret = "complete-render-body-secret"
        result = decode_qrender_response(response(("x" * 200 + secret).encode()), "root", 123)
        self.assertNotIn(secret, repr(result))

    def test_zero_height_is_accepted_as_unreported(self):
        result = decode_qrender_response(response(height="0"), "root", 123)
        self.assertIsNone(result.response_height)

    def test_matching_canonical_positive_height_is_accepted(self):
        result = decode_qrender_response(response(height="123"), "root", 123)
        self.assertEqual(result.response_height, 123)

    def test_different_canonical_positive_height_is_rejected(self):
        with self.assertRaisesRegex(RpcError, "height mismatch"):
            decode_qrender_response(response(height="122"), "root", 123)

    def test_noncanonical_or_non_string_heights_are_rejected(self):
        invalid_heights = (
            None,
            0,
            123,
            True,
            1.0,
            [],
            {},
            "",
            "00",
            "0123",
            "+123",
            "-1",
            " 123",
            "123 ",
            "1.0",
            "abc",
        )
        for height in invalid_heights:
            with self.subTest(height=height), self.assertRaisesRegex(RpcError, "invalid.*Height"):
                decode_qrender_response(response(height=height), "root", 123)

    def test_missing_height_is_rejected(self):
        payload = response()
        del payload["result"]["response"]["Height"]
        with self.assertRaisesRegex(RpcError, r"result\.response\.Height"):
            decode_qrender_response(payload, "root", 123)

    def test_response_base_is_required_and_must_be_a_dictionary(self):
        for response_base in (None, "not-a-dictionary"):
            payload = response()
            payload["result"]["response"]["ResponseBase"] = response_base
            with self.subTest(response_base=response_base), self.assertRaisesRegex(
                RpcError, r"result\.response\.ResponseBase"
            ):
                decode_qrender_response(payload, "root", 123)

    def test_abci_error_is_rejected_without_exposing_error_or_log(self):
        sensitive_error = {"message": "complete-sensitive-error"}
        payload = response(error=sensitive_error, log="complete-sensitive-log")
        with self.assertRaisesRegex(RpcError, "ABCI response reported an error") as raised:
            decode_qrender_response(payload, "root", 123)
        message = str(raised.exception)
        self.assertNotIn("complete-sensitive-error", message)
        self.assertNotIn("complete-sensitive-log", message)

    def test_null_and_empty_string_abci_error_are_allowed(self):
        for error in (None, ""):
            with self.subTest(error=error):
                result = decode_qrender_response(response(error=error), "root", 123)
                self.assertIsNone(result.response_height)

    def test_missing_abci_error_field_fails_closed(self):
        payload = response()
        del payload["result"]["response"]["ResponseBase"]["Error"]
        with self.assertRaisesRegex(RpcError, "ABCI response reported an error"):
            decode_qrender_response(payload, "root", 123)

    def test_invalid_response_base64_is_rejected(self):
        payload = response()
        payload["result"]["response"]["ResponseBase"]["Data"] = "not base64!"
        with self.assertRaisesRegex(RpcError, "invalid base64"):
            decode_qrender_response(payload, "root", 123)

    def test_invalid_decoded_utf8_is_rejected(self):
        with self.assertRaisesRegex(RpcError, "not UTF-8"):
            decode_qrender_response(response(b"\xff"), "root", 123)

    def test_missing_response_fields_are_rejected(self):
        payloads = ({}, {"result": {}}, {"result": {"response": None}})
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaisesRegex(
                RpcError, "missing result.response"
            ):
                decode_qrender_response(payload, "root", 123)

    def test_response_base_data_is_required_and_non_empty(self):
        for data in (None, ""):
            payload = response()
            if data is None:
                del payload["result"]["response"]["ResponseBase"]["Data"]
            else:
                payload["result"]["response"]["ResponseBase"]["Data"] = data
            with self.subTest(data=data), self.assertRaisesRegex(
                RpcError, r"result\.response\.ResponseBase\.Data"
            ):
                decode_qrender_response(payload, "root", 123)

    def test_value_is_not_used_as_a_fallback(self):
        payload = response()
        encoded = payload["result"]["response"]["ResponseBase"].pop("Data")
        payload["result"]["response"]["Value"] = encoded
        with self.assertRaisesRegex(RpcError, r"result\.response\.ResponseBase\.Data"):
            decode_qrender_response(payload, "root", 123)

    def test_encoded_response_limit_is_enforced_before_decode(self):
        payload = response()
        payload["result"]["response"]["ResponseBase"]["Data"] = "A" * (
            MAX_ENCODED_RESPONSE_CHARS + 1
        )
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
        self.assertIn("kind=root source_height=123 response_height=unreported", output)

    def test_cli_page_only_does_not_request_root(self):
        code, output, _, client = self.run_main(["--page-query", "?page=2"])
        self.assertEqual(code, 0)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("kind=root", output)
        self.assertIn("kind=page", output)

    def test_cli_detail_only_does_not_request_root(self):
        code, output, _, client = self.run_main(["--operator-address", OPERATOR_ADDRESS])
        self.assertEqual(code, 0)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("kind=root", output)
        self.assertIn("kind=detail", output)

    def test_cli_page_and_detail_request_exactly_two_renders_at_one_height(self):
        code, output, _, client = self.run_main(
            ["--page-query", "?page=2", "--operator-address", OPERATOR_ADDRESS]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn("kind=root", output)
        self.assertIn("kind=page", output)
        self.assertIn("kind=detail", output)
        self.assertTrue(all(call[1]["height"] == 123 for call in client.calls))

    def test_cli_suppresses_credential_bearing_rpc_selection_output(self):
        raw_url = "https://user:secret@example.invalid/rpc?token=private"
        client = FakeClient()

        def noisy_selection(urls, **_kwargs):
            print(f"Selected RPC: {urls[0]}")
            return client, self.status_payload

        stdout = StringIO()
        stderr = StringIO()
        with patch("scripts.probe_valopers.configured_rpc_urls", return_value=[raw_url]), patch(
            "scripts.probe_valopers.configured_chain_id", return_value="test-13"
        ), patch(
            "scripts.probe_valopers.select_healthy_rpc", side_effect=noisy_selection
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            code = probe_valopers.main([])

        self.assertEqual(code, 0)
        combined_output = stdout.getvalue() + stderr.getvalue()
        for sensitive_value in ("user", "secret", "token=private", raw_url):
            self.assertNotIn(sensitive_value, combined_output)

    def test_cli_failure_is_nonzero_and_does_not_dump_payload(self):
        secret = "complete-render-body-secret"
        client = FakeClient(response(secret.encode(), height="122"))
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

    def test_documented_script_path_help_runs_from_repository_root(self):
        completed = subprocess.run(
            [sys.executable, "scripts/probe_valopers.py", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--page-query", completed.stdout)


if __name__ == "__main__":
    unittest.main()
