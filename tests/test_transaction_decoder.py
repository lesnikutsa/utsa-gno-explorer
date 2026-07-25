import base64
import json
import os
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from indexer.config import TransactionDecoderConfig, load_transaction_decoder_config
from indexer.transaction_decoder import JsonlTransactionDecoder, build_transaction_decoder


SUMMARY = {
    "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
    "message_count": 1, "messages_truncated": False,
    "primary": {"type": "gno.vm.MsgCall", "category": "vm", "action": "call", "label": "Contract Call"},
    "messages": [{"type": "gno.vm.MsgCall"}],
}


class DecoderTests(unittest.TestCase):
    def helper(self, body):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "helper"
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
        path.chmod(0o755)
        self.addCleanup(directory.cleanup)
        return str(path)

    def decoder(self, path, timeout=.5, backoff=1):
        decoder = JsonlTransactionDecoder([path], "gno", timeout, backoff)
        self.addCleanup(decoder.close)
        return decoder

    def test_disabled_factory(self):
        config = TransactionDecoderConfig(False, "/missing", "gno", 2, 30)
        self.assertIsNone(build_transaction_decoder(config))

    def test_reuses_process_and_orders_ids(self):
        count = Path(tempfile.mktemp())
        path = self.helper(f'''\
            import json
            from pathlib import Path
            p=Path({str(count)!r}); p.write_text(str(int(p.read_text())+1) if p.exists() else "1")
            for line in __import__("sys").stdin:
                request=json.loads(line)
                print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}), flush=True)
        ''')
        decoder = self.decoder(path)
        self.assertEqual(decoder.decode(base64.b64encode(b"a").decode(), 1)["parse_status"], "parsed")
        self.assertEqual(decoder.decode(base64.b64encode(b"b").decode(), 1)["parse_status"], "parsed")
        self.assertEqual(count.read_text(), "1")

    def test_safe_error_keeps_process(self):
        path = self.helper(f'''\
            import json,sys
            for number,line in enumerate(sys.stdin):
                request=json.loads(line)
                if number == 0: response={{"protocol_version":1,"id":request["id"],"ok":False,"error_code":"amino_decode_failed"}}
                else: response={{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}
                print(json.dumps(response),flush=True)
        ''')
        decoder = self.decoder(path)
        self.assertIsNone(decoder.decode("YQ==", 1))
        pid = decoder._process.pid
        self.assertIsNotNone(decoder.decode("Yg==", 1))
        self.assertEqual(decoder._process.pid, pid)

    def test_timeout_and_cooldown(self):
        path = self.helper('''\
            import time
            for line in __import__("sys").stdin: time.sleep(10)
        ''')
        decoder = self.decoder(path, timeout=.05)
        started = time.monotonic()
        self.assertIsNone(decoder.decode("YQ==", 1))
        self.assertLess(time.monotonic()-started, .5)
        self.assertIsNone(decoder._process)
        self.assertIsNone(decoder.decode("YQ==", 1))

    def test_protocol_failure_and_missing_executable_are_safe(self):
        malformed = self.helper('for line in __import__("sys").stdin: print("not-json",flush=True)')
        decoder = self.decoder(malformed)
        self.assertIsNone(decoder.decode("YQ==", 1))
        missing = self.decoder("/definitely/missing")
        self.assertIsNone(missing.decode("YQ==", 1))

    def test_input_bounds_do_not_start_process(self):
        decoder = self.decoder("/definitely/missing")
        self.assertIsNone(decoder.decode("YQ==", 4 * 1024 * 1024 + 1))
        self.assertIsNone(decoder._process)

    def test_close_is_idempotent(self):
        path = self.helper(f'''\
            import json,sys
            for line in sys.stdin:
                request=json.loads(line); print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}),flush=True)
        ''')
        decoder = self.decoder(path)
        decoder.decode("YQ==", 1)
        process = decoder._process
        decoder.close(); decoder.close()
        self.assertIsNotNone(process.poll())


class DecoderConfigTests(unittest.TestCase):
    def load(self, **values):
        with patch.dict(os.environ, values, clear=True), patch("indexer.config.load_dotenv"):
            return load_transaction_decoder_config()

    def test_defaults(self):
        self.assertFalse(self.load().enabled)

    def test_enabled(self):
        config = self.load(TRANSACTION_DECODER_ENABLED="YES", TRANSACTION_DECODER_PATH="/decoder")
        self.assertTrue(config.enabled)

    def test_invalid_values(self):
        for values in (
            {"TRANSACTION_DECODER_ENABLED":"maybe"},
            {"TRANSACTION_DECODER_ENABLED":"true", "TRANSACTION_DECODER_PATH":"relative"},
            {"TRANSACTION_DECODER_CHAIN_FAMILY":"GNO"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"0"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"31"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"0"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"3601"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError): self.load(**values)
