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
        ids = Path(tempfile.mktemp())
        path = self.helper(f'''\
            import json
            from pathlib import Path
            p=Path({str(count)!r}); p.write_text(str(int(p.read_text())+1) if p.exists() else "1")
            for line in __import__("sys").stdin:
                request=json.loads(line)
                q=Path({str(ids)!r}); q.write_text(q.read_text()+request["id"]+"\\n" if q.exists() else request["id"]+"\\n")
                print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}), flush=True)
        ''')
        decoder = self.decoder(path)
        self.assertIsNone(decoder.decode(None, 1))
        self.assertEqual(decoder.decode(base64.b64encode(b"a").decode(), 1)["parse_status"], "parsed")
        self.assertEqual(decoder.decode(base64.b64encode(b"b").decode(), 1)["parse_status"], "parsed")
        self.assertEqual(count.read_text(), "1")
        self.assertEqual(ids.read_text().splitlines(), ["tx-1", "tx-2"])

    def test_unsupported_summary_is_successful(self):
        unsupported = {**SUMMARY, "parse_status": "unsupported"}
        path = self.helper(f'''\
            import json,sys
            for line in sys.stdin:
                request=json.loads(line); print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{unsupported!r}}}),flush=True)
        ''')
        decoder = self.decoder(path)
        self.assertEqual(decoder.decode("YQ==", 1)["parse_status"], "unsupported")
        self.assertEqual(decoder._retry_at, 0)

    def test_child_environment_excludes_secrets_and_preserves_env_shebang(self):
        observed = Path(tempfile.mktemp())
        path = self.helper(f'''\
            import json,os,sys
            from pathlib import Path
            Path({str(observed)!r}).write_text(json.dumps(dict(os.environ),sort_keys=True))
            for line in sys.stdin:
                request=json.loads(line); print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}),flush=True)
        ''')
        with patch.dict(os.environ, {"DATABASE_URL": "SECRET-DB", "GNO_RPC_URLS": "SECRET-RPC", "API_TOKEN": "SECRET-TOKEN"}):
            decoder = self.decoder(path)
            self.assertIsNotNone(decoder.decode("YQ==", 1))
        environment = json.loads(observed.read_text())
        self.assertEqual(set(environment), {"PATH", "LANG", "LC_ALL"})
        self.assertNotIn("SECRET", json.dumps(environment))

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

    def test_protocol_failure_matrix_enters_cooldown(self):
        cases = {
            "internal_error": '{"protocol_version":1,"id":"tx-1","ok":false,"error_code":"internal_error"}',
            "invalid_json_code": '{"protocol_version":1,"id":"tx-1","ok":false,"error_code":"invalid_json"}',
            "malformed_json": 'not-json',
            "not_object": '[]',
            "wrong_version": '{"protocol_version":2,"id":"tx-1","ok":true}',
            "wrong_id": '{"protocol_version":1,"id":"other","ok":true}',
            "missing_ok": '{"protocol_version":1,"id":"tx-1"}',
            "non_boolean_ok": '{"protocol_version":1,"id":"tx-1","ok":1}',
            "missing_summary": '{"protocol_version":1,"id":"tx-1","ok":true}',
            "unexpected_code": '{"protocol_version":1,"id":"tx-1","ok":false,"error_code":"other"}',
            "wrong_family": json.dumps({"protocol_version": 1, "id": "tx-1", "ok": True, "summary": {**SUMMARY, "chain_family": "cosmos"}}),
            "malformed_summary": '{"protocol_version":1,"id":"tx-1","ok":true,"summary":{"bad":true}}',
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                count = Path(tempfile.mktemp())
                path = self.helper(f'''\
                    from pathlib import Path
                    p=Path({str(count)!r}); p.write_text(str(int(p.read_text())+1) if p.exists() else "1")
                    for line in __import__("sys").stdin: print({response!r},flush=True)
                ''')
                decoder = self.decoder(path)
                self.assertIsNone(decoder.decode("YQ==", 1))
                self.assertIsNone(decoder._process)
                self.assertGreater(decoder._retry_at, 0)
                self.assertIsNone(decoder.decode("YQ==", 1))
                self.assertEqual(count.read_text(), "1")

    def test_oversized_response_and_eof_enter_cooldown(self):
        for body in ('for line in __import__("sys").stdin: print("x"*32769,flush=True)',
                     'for line in __import__("sys").stdin: break'):
            with self.subTest(body=body):
                decoder = self.decoder(self.helper(body))
                self.assertIsNone(decoder.decode("YQ==", 1))
                self.assertIsNone(decoder._process)
                self.assertGreater(decoder._retry_at, 0)

    def test_input_bounds_do_not_start_process(self):
        decoder = self.decoder("/definitely/missing")
        self.assertIsNone(decoder.decode("YQ==", 4 * 1024 * 1024 + 1))
        self.assertIsNone(decoder._process)

    def test_malformed_caller_input_is_total_and_does_not_serialize(self):
        decoder = self.decoder("/definitely/missing")
        invalid = ((None, 1), (b"YQ==", 1), ("YQ==", None), ("YQ==", "1"),
                   ("YQ==", True), ("YQ==", -1), ("YQ==", 4 * 1024 * 1024 + 1))
        with patch("indexer.transaction_decoder.json.dumps") as dumps:
            for tx, size in invalid:
                with self.subTest(tx_type=type(tx), size=size):
                    self.assertIsNone(decoder.decode(tx, size))
            dumps.assert_not_called()
        self.assertEqual(decoder._request_number, 0)

    def test_obvious_request_bound_and_cooldown_do_not_serialize_or_consume_id(self):
        decoder = self.decoder("/definitely/missing")
        with patch("indexer.transaction_decoder.json.dumps") as dumps:
            self.assertIsNone(decoder.decode("x" * (8 * 1024 * 1024 + 1), 1))
            dumps.assert_not_called()
        decoder._retry_at = time.monotonic() + 10
        with patch("indexer.transaction_decoder.json.dumps") as dumps:
            self.assertIsNone(decoder.decode("YQ==", 1))
            dumps.assert_not_called()
        self.assertEqual(decoder._request_number, 0)

    def test_write_timeout_is_bounded(self):
        path = self.helper('''\
            import time
            time.sleep(10)
        ''')
        decoder = self.decoder(path, timeout=.05)
        started = time.monotonic()
        self.assertIsNone(decoder.decode("a" * 200_000, 150_000))
        self.assertLess(time.monotonic() - started, .5)
        self.assertIsNone(decoder._process)

    def test_all_safe_errors_keep_same_process(self):
        for code in ("invalid_base64", "input_too_large", "amino_decode_failed",
                     "invalid_request", "missing_tx_base64"):
            with self.subTest(code=code):
                path = self.helper(f'''\
                    import json,sys
                    for number,line in enumerate(sys.stdin):
                        request=json.loads(line)
                        response={{"protocol_version":1,"id":request["id"],"ok":False,"error_code":{code!r}}} if number == 0 else {{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}
                        print(json.dumps(response),flush=True)
                ''')
                decoder = self.decoder(path)
                self.assertIsNone(decoder.decode("YQ==", 1))
                pid = decoder._process.pid
                self.assertEqual(decoder._retry_at, 0)
                self.assertEqual(decoder.decode("Yg==", 1)["parse_status"], "parsed")
                self.assertEqual(decoder._process.pid, pid)
                decoder.close()

    def test_fake_clock_cooldown_and_restart(self):
        starts = Path(tempfile.mktemp())
        path = self.helper(f'''\
            import json,sys
            from pathlib import Path
            p=Path({str(starts)!r}); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n))
            for line in sys.stdin:
                request=json.loads(line)
                if n == 1: print("bad-json",flush=True)
                else: print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}),flush=True)
        ''')
        now = [100.0]
        decoder = JsonlTransactionDecoder([path], "gno", .5, 30, monotonic=lambda: now[0])
        self.addCleanup(decoder.close)
        self.assertIsNone(decoder.decode("YQ==", 1))
        self.assertEqual(starts.read_text(), "1")
        self.assertIsNone(decoder.decode("YQ==", 1))
        now[0] = 129.999
        self.assertIsNone(decoder.decode("YQ==", 1))
        self.assertEqual(starts.read_text(), "1")
        now[0] = 130.0
        self.assertEqual(decoder.decode("YQ==", 1)["parse_status"], "parsed")
        self.assertEqual(starts.read_text(), "2")

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
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_close_kills_child_ignoring_sigterm(self):
        path = self.helper(f'''\
            import json,signal,sys,time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            for line in sys.stdin:
                request=json.loads(line); print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}),flush=True)
                time.sleep(10)
        ''')
        decoder = self.decoder(path)
        self.assertIsNotNone(decoder.decode("YQ==", 1))
        process = decoder._process
        decoder.close(); decoder.close()
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_close_kills_when_terminate_raises(self):
        class Pipe:
            closed = False
            def close(self): self.closed = True
        class Process:
            def __init__(self):
                self.stdin, self.stdout, self.stderr = Pipe(), Pipe(), Pipe()
                self.killed = False
            def poll(self): return 0 if self.killed else None
            def terminate(self): raise OSError("terminate failed")
            def wait(self, timeout):
                if not self.killed: raise TimeoutError
                return 0
            def kill(self): self.killed = True
        decoder = self.decoder("/unused")
        process = Process()
        decoder._process = process
        decoder.close(); decoder.close()
        self.assertTrue(process.killed)
        self.assertTrue(all(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr)))

    def test_stderr_and_payload_are_not_logged(self):
        sentinel = "CHILD-SECRET-SENTINEL"
        payload = "PRIVATE-BASE64"
        path = self.helper(f'''\
            import json,sys
            for line in sys.stdin:
                print({sentinel!r},file=sys.stderr,flush=True)
                request=json.loads(line); print(json.dumps({{"protocol_version":1,"id":request["id"],"ok":True,"summary":{SUMMARY!r}}}),flush=True)
        ''')
        decoder = self.decoder(path)
        with self.assertLogs("indexer.transaction_decoder", level="INFO") as logs:
            self.assertIsNotNone(decoder.decode(payload, 1))
        output = "\n".join(logs.output)
        self.assertNotIn(sentinel, output)
        self.assertNotIn(payload, output)


class DecoderConfigTests(unittest.TestCase):
    def load(self, **values):
        with patch.dict(os.environ, values, clear=True), patch("indexer.config.load_dotenv"):
            return load_transaction_decoder_config()

    def test_defaults(self):
        config = self.load()
        self.assertEqual(config, TransactionDecoderConfig(False, "/opt/utsa-gno-explorer/bin/gno-tx-decoder", "gno", 2, 30))
        expected = {
            "TRANSACTION_DECODER_ENABLED": "false",
            "TRANSACTION_DECODER_PATH": "/opt/utsa-gno-explorer/bin/gno-tx-decoder",
            "TRANSACTION_DECODER_CHAIN_FAMILY": "gno",
            "TRANSACTION_DECODER_TIMEOUT_SECONDS": "2",
            "TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS": "30",
        }
        for filename in (".env.example", "deploy/systemd/indexer.env.example"):
            values = dict(line.split("=", 1) for line in Path(filename).read_text().splitlines() if line.startswith("TRANSACTION_DECODER_"))
            self.assertEqual(values, expected)

    def test_enabled(self):
        config = self.load(TRANSACTION_DECODER_ENABLED="YES", TRANSACTION_DECODER_PATH="/decoder")
        self.assertTrue(config.enabled)

    def test_all_explicit_boolean_forms(self):
        for raw, expected in (("true", True), ("false", False), ("1", True), ("0", False),
                              ("yes", True), ("no", False), ("on", True), ("off", False),
                              ("TRUE", True), ("OFF", False)):
            with self.subTest(raw=raw):
                self.assertEqual(self.load(TRANSACTION_DECODER_ENABLED=raw).enabled, expected)

    def test_invalid_values(self):
        for values in (
            {"TRANSACTION_DECODER_ENABLED":"maybe"},
            {"TRANSACTION_DECODER_ENABLED":"true", "TRANSACTION_DECODER_PATH":"relative"},
            {"TRANSACTION_DECODER_CHAIN_FAMILY":"GNO"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"0"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"31"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"0"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"3601"},
            {"TRANSACTION_DECODER_ENABLED":"true", "TRANSACTION_DECODER_PATH":""},
            {"TRANSACTION_DECODER_CHAIN_FAMILY":""},
            {"TRANSACTION_DECODER_CHAIN_FAMILY":"a" * 65},
            {"TRANSACTION_DECODER_CHAIN_FAMILY":"bad.family"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"nan"},
            {"TRANSACTION_DECODER_TIMEOUT_SECONDS":"inf"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"nan"},
            {"TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS":"inf"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError): self.load(**values)
