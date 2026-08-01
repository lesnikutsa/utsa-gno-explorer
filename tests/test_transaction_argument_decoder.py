import base64
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from api.config import ApiConfig
from api.transaction_argument_decoder import MAX_RESPONSE_BYTES, decode_transaction_arguments


RAW = b"stored amino transaction"
RAW_BASE64 = base64.b64encode(RAW).decode("ascii")
SECRET_ARGUMENT = "secret-argument-value"
SECRET_ENVIRONMENT = "secret-environment-value"


class TransactionArgumentDecoderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def config(self, path, **overrides):
        return ApiConfig(database_url="unused", transaction_detail_decoder_path=str(path), **overrides)

    def decoder_script(self, body):
        path = Path(self.temporary_directory.name) / f"decoder-{len(list(Path(self.temporary_directory.name).iterdir()))}"
        path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def successful_script(self, message_arguments=None):
        entries = message_arguments if message_arguments is not None else [
            {"message_index": 0, "values": [SECRET_ARGUMENT, ""], "truncated": False},
        ]
        return self.decoder_script(
            "import json, sys\n"
            "request = json.loads(sys.stdin.readline())\n"
            f"entries = {entries!r}\n"
            "json.dump({'protocol_version': 1, 'id': request['id'], 'ok': True, "
            "'summary': {'existing': 'summary'}, 'details': {'message_arguments': entries}}, sys.stdout)"
        )

    def test_one_shot_request_and_sanitized_environment(self):
        path = self.successful_script()
        real_popen = subprocess.Popen
        with patch.dict(os.environ, {"SECRET_TEST_VALUE": SECRET_ENVIRONMENT}, clear=False), patch(
            "api.transaction_argument_decoder.subprocess.Popen", wraps=real_popen,
        ) as popen:
            result = decode_transaction_arguments(RAW_BASE64, len(RAW), self.config(path))
        self.assertEqual(result[0]["values"], [SECRET_ARGUMENT, ""])
        popen.assert_called_once()
        _command, kwargs = popen.call_args
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertNotIn("DATABASE_URL", kwargs["env"])
        self.assertNotIn("SECRET_TEST_VALUE", kwargs["env"])
        self.assertLessEqual(set(kwargs["env"]), {"PATH", "LANG", "LC_ALL"})

    def test_oversized_streaming_stdout_is_bounded_terminated_and_reaped(self):
        pid_path = Path(self.temporary_directory.name) / "decoder.pid"
        path = self.decoder_script(
            "import os, sys, time\n"
            f"open({str(pid_path)!r}, 'w').write(str(os.getpid()))\n"
            "sys.stdin.readline()\n"
            f"sys.stdout.buffer.write(b'x' * ({MAX_RESPONSE_BYTES} + 4096))\n"
            "sys.stdout.flush()\n"
            "time.sleep(10)"
        )
        started = time.monotonic()
        self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config(path)))
        self.assertLess(time.monotonic() - started, 1.0)
        pid = int(pid_path.read_text(encoding="utf-8"))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_timeout_is_bounded_and_child_is_reaped(self):
        pid_path = Path(self.temporary_directory.name) / "timeout.pid"
        path = self.decoder_script(
            "import os, sys, time\n"
            f"open({str(pid_path)!r}, 'w').write(str(os.getpid()))\n"
            "sys.stdin.readline()\n"
            "time.sleep(10)"
        )
        started = time.monotonic()
        self.assertIsNone(decode_transaction_arguments(
            RAW_BASE64,
            len(RAW),
            self.config(path, transaction_detail_decoder_timeout_seconds=0.1),
        ))
        self.assertLess(time.monotonic() - started, 0.8)
        pid = int(pid_path.read_text(encoding="utf-8"))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_unavailable_malformed_and_missing_details_return_none(self):
        paths = [
            Path(self.temporary_directory.name) / "missing",
            self.decoder_script("import sys\nsys.stdin.readline()\nsys.exit(1)"),
            self.decoder_script("import sys\nsys.stdin.readline()\nsys.stdout.write('not json')"),
            self.decoder_script(
                "import json, sys\nsys.stdin.readline()\n"
                "json.dump({'protocol_version': 1, 'id': 'wrong', 'ok': True}, sys.stdout)"
            ),
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config(path)))

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
            with self.subTest(entries=entries):
                path = self.successful_script(entries)
                self.assertIsNone(decode_transaction_arguments(RAW_BASE64, len(RAW), self.config(path)))

    def test_invalid_stored_input_does_not_start_decoder(self):
        with patch("api.transaction_argument_decoder.subprocess.Popen") as popen:
            for raw, length in (("%%%", 3), (RAW_BASE64, None), (RAW_BASE64, len(RAW) + 1)):
                self.assertIsNone(decode_transaction_arguments(raw, length, self.config("/safe/decoder")))
        popen.assert_not_called()

    def test_failures_do_not_log_payload_arguments_environment_or_stderr(self):
        logger = logging.getLogger("api.transaction_argument_decoder")
        with patch("api.transaction_argument_decoder.subprocess.Popen", side_effect=OSError(SECRET_ARGUMENT)):
            with self.assertNoLogs(logger):
                self.assertIsNone(decode_transaction_arguments(
                    RAW_BASE64,
                    len(RAW),
                    self.config("/safe/decoder"),
                ))
