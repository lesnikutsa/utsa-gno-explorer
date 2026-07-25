import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from indexer.transaction_summary import generic_summary
from indexer.transaction_summary_backfill import (
    CANDIDATE_SQL, Candidate, process_candidates,
)
from scripts import backfill_transaction_summaries as cli
from scripts.backfill_transaction_summaries import build_parser


def stable(status="parsed"):
    value = generic_summary(status)
    value["chain_family"] = "gno"
    value["primary"] = {"type": "bank/send", "category": "bank", "action": "send", "label": "Send"}
    return value


class BackfillArgumentTests(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args([])
        self.assertFalse(args.apply)
        self.assertEqual((args.limit, args.sleep_ms), (25, 250))

    def test_boundaries(self):
        for value in (1, 100):
            self.assertEqual(build_parser().parse_args(["--limit", str(value)]).limit, value)
        for value in (0, 5000):
            self.assertEqual(build_parser().parse_args(["--sleep-ms", str(value)]).sleep_ms, value)
        for option, value in (("--limit", 0), ("--limit", 101), ("--sleep-ms", -1), ("--sleep-ms", 5001)):
            with self.assertRaises(SystemExit):
                build_parser().parse_args([option, str(value)])

    def test_modes_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--dry-run", "--apply"])


class BackfillQueryTests(unittest.TestCase):
    def test_query_is_bounded_and_nonlocking(self):
        upper = CANDIDATE_SQL.upper()
        self.assertNotIn("OFFSET", upper)
        self.assertNotIn("COUNT", upper)
        self.assertNotIn("FOR UPDATE", upper)
        self.assertIn("ORDER BY BLOCK_HEIGHT DESC, TX_INDEX DESC", upper)
        self.assertIn("LIMIT %S", upper)

    def test_query_selects_only_decodable_exact_fallbacks(self):
        for fragment in (
            "decode_status = 'decoded'", "raw_base64 IS NOT NULL",
            "raw_base64 ~",
            "decoded_byte_length IS NOT NULL", "decoded_byte_length >= 0",
            "payload_summary IS NULL", "payload_summary->>'schema_version' = '1'",
            "payload_summary->>'chain_family' = 'unknown'",
            "payload_summary->>'parse_status' = 'unparsed'",
        ):
            self.assertIn(fragment, CANDIDATE_SQL)


class BackfillProcessingTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [Candidate(1, 20, 2, "YQ==", 1), Candidate(2, 19, 1, "Yg==", 1)]

    def test_dry_run_decodes_sequentially_without_update(self):
        decoder = MagicMock()
        decoder.decode.side_effect = [stable(), stable("unsupported")]
        connection = MagicMock()
        sleeps = []
        result = process_candidates(connection, decoder, self.candidates, apply=False, sleep_ms=250, sleeper=sleeps.append)
        self.assertEqual(decoder.decode.call_args_list[0].args, ("YQ==", 1))
        self.assertEqual(decoder.decode.call_args_list[1].args, ("Yg==", 1))
        self.assertEqual((result.parsed, result.unsupported, result.updated, result.dry_run), (1, 1, 0, 2))
        connection.cursor.assert_not_called()
        self.assertEqual(sleeps, [0.25])

    def test_none_is_safe_failure(self):
        decoder = MagicMock()
        decoder.decode.return_value = None
        connection = MagicMock()
        result = process_candidates(connection, decoder, self.candidates[:1], apply=True, sleep_ms=0)
        self.assertEqual(result.decode_failed, 1)
        connection.cursor.assert_not_called()

    def test_apply_counts_update_and_race(self):
        decoder = MagicMock()
        decoder.decode.side_effect = [stable(), stable("unsupported")]
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.rowcount = 1
        connection = MagicMock()
        connection.cursor.return_value = cursor
        first = process_candidates(connection, decoder, self.candidates[:1], apply=True, sleep_ms=0)
        self.assertEqual(first.updated, 1)
        update_sql = cursor.execute.call_args.args[0]
        self.assertIn("SET payload_summary = %s", update_sql)
        cursor.rowcount = 0
        second = process_candidates(connection, decoder, self.candidates[1:], apply=True, sleep_ms=0)
        self.assertEqual(second.skipped_race, 1)


class BackfillCliTests(unittest.TestCase):
    def run_cli(self, process_side_effect=None):
        connection = MagicMock()
        decoder = MagicMock()
        decoder_config = SimpleNamespace(
            executable_path="/bin/true", expected_chain_family="gno",
            timeout_seconds=2, restart_backoff_seconds=30,
        )
        output, errors = StringIO(), StringIO()
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://secret@database/example"}), \
             patch.object(cli, "load_transaction_decoder_config", return_value=decoder_config), \
             patch.object(cli.PostgresDatabase, "connect", return_value=connection), \
             patch.object(cli, "try_advisory_lock", return_value=True), \
             patch.object(cli, "release_advisory_lock"), \
             patch.object(cli, "select_candidates", return_value=[]), \
             patch.object(cli, "JsonlTransactionDecoder", return_value=decoder), \
             patch.object(cli, "process_candidates", side_effect=process_side_effect, return_value=SimpleNamespace(
                 selected=0, decoded=0, parsed=0, unsupported=0, updated=0,
                 dry_run=0, decode_failed=0, skipped_race=0,
             )), redirect_stdout(output), redirect_stderr(errors):
            code = cli.main([])
        return code, decoder, output.getvalue() + errors.getvalue()

    def test_decoder_closes_after_success_and_failure_without_sensitive_output(self):
        code, decoder, output = self.run_cli()
        self.assertEqual(code, 0)
        decoder.close.assert_called_once()
        self.assertNotIn("secret", output)
        code, decoder, output = self.run_cli(RuntimeError("decoder raw errors DATABASE_URL"))
        self.assertNotEqual(code, 0)
        decoder.close.assert_called_once()
        self.assertNotIn("decoder raw errors", output)
        self.assertNotIn("DATABASE_URL", output)

    def test_empty_candidate_set_succeeds(self):
        code, _, _ = self.run_cli()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
