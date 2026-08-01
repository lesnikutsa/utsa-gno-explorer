import base64
import json
import logging
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.config import ApiConfig
from api.transaction_argument_decoder import decode_transaction_arguments


RAW = b"stored amino transaction"
RAW_BASE64 = base64.b64encode(RAW).decode("ascii")
SECRET_ARGUMENT = "secret-argument-value"
SECRET_ENVIRONMENT = "secret-environment-value"


class TransactionArgumentDecoderTests(unittest.TestCase):
    def config(self, **overrides):
        return ApiConfig(database_url="unused", transaction_detail_decoder_path="/safe/decoder", **overrides)

    def successful_output(self, request, message_arguments=None):
        request_value = json.loads(request)
        return json.dumps({
            "protocol_version": 1,
            "id": request_value["id"],
            "ok": True,
            "summary": {"existing": "summary"},
            "details": {"message_arguments": message_arguments if message_arguments is not None else [
                {"message_index": 0, "values": [SECRET_ARGUMENT, ""], "truncated": False},
            ]},
        }).encode()

    def test_one_shot_request_and_sanitized_environment(self):
        def run(command, **kwargs):
            self.assertEqual(command, ["/safe/decoder"])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 1.5)
            self.assertTrue(json.loads(kwargs["input"])["include_arguments"])
            self.assertNotIn("DATABASE_URL", kwargs["env"])
            self.assertNotIn("SECRET_TEST_VALUE", kwargs["env"])
            self.assertLessEqual(set(kwargs["env"]), {"PATH", "LANG", "LC_ALL"})
            return SimpleNamespace(returncode=0, stdout=self.successful_output(kwargs["input"]))

        with patch.dict("os.environ", {"SECRET_TEST_VALUE": SECRET_ENVIRONMENT}, clear=False), patch(
            "api.transaction_argument_decoder.subprocess.run", side_effect=run,
        ):
            result = decode_transaction_arguments(RAW_BASE64, len(RAW), self.config())
        self.assertEqual(result[0]["values"], [SECRET_ARGUMENT, ""])

    def test_unavailable_timeout_malformed_and_missing_details_return_none(self):
        failures = [
            OSError("not executable"),
            subprocess.TimeoutExpired("decoder", 1.5),
            SimpleNamespace(returncode=1, stdout=b""),
            SimpleNamespace(returncode=0, stdout=b"not json"),
            SimpleNamespace(returncode=0, stdout=json.dumps({"protocol_version": 1, "id": "wrong", "ok": True}).encode()),
        ]
        for failure in failures:
            effect = failure if isinstance(failure, BaseException) else None
            with patch(
                "api.transaction_argument_decoder.subprocess.run",
                side_effect=effect,
                return_value=None if effect else failure,
            ):
                self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config()))

    def test_malformed_details_are_rejected(self):
        malformed = [
            [{"message_index": 0, "values": [], "truncated": False, "unknown": 1}],
            [{"message_index": 1, "values": [], "truncated": False}, {"message_index": 1, "values": [], "truncated": False}],
            [{"message_index": 2, "values": [], "truncated": False}, {"message_index": 1, "values": [], "truncated": False}],
            [{"message_index": 0, "values": ["x" * 257], "truncated": False}],
            [{"message_index": 0, "values": ["control\n"], "truncated": False}],
            [{"message_index": 0, "values": [], "truncated": 1}],
        ]
        for entries in malformed:
            def run(_command, **kwargs):
                return SimpleNamespace(returncode=0, stdout=self.successful_output(kwargs["input"], entries))
            with patch("api.transaction_argument_decoder.subprocess.run", side_effect=run):
                self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config()))

    def test_invalid_stored_input_does_not_start_decoder(self):
        with patch("api.transaction_argument_decoder.subprocess.run") as run:
            for raw, length in (("%%%", 3), (RAW_BASE64, None), (RAW_BASE64, len(RAW) + 1)):
                self.assertIsNone(decode_transaction_arguments(raw, length, self.config()))
        run.assert_not_called()

    def test_failures_do_not_log_payload_arguments_environment_or_stderr(self):
        logger = logging.getLogger("api.transaction_argument_decoder")
        with patch("api.transaction_argument_decoder.subprocess.run", side_effect=OSError(SECRET_ARGUMENT)):
            with self.assertNoLogs(logger):
                self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config()))
