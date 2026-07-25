import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from indexer.config import IndexerConfig
from indexer.runner import ContinuousConfig
from scripts import index_range, run_indexer


class DecoderCliLifecycleTests(unittest.TestCase):
    def test_run_indexer_closes_once_for_returns_and_failure(self):
        for outcome in (0, 1, RuntimeError("failed")):
            with self.subTest(outcome=outcome):
                decoder = MagicMock()
                effect = outcome if isinstance(outcome, Exception) else None
                returned = 0 if isinstance(outcome, Exception) else outcome
                with patch.object(run_indexer, "load_transaction_decoder_config"), \
                     patch.object(run_indexer, "build_transaction_decoder", return_value=decoder) as factory, \
                     patch.object(run_indexer, "load_continuous_config", return_value=ContinuousConfig(1, 1, 1, 1, 1)), \
                     patch.object(run_indexer, "load_config", return_value=IndexerConfig("db", ["rpc"], "chain", 1, 1)), \
                     patch.object(run_indexer, "PostgresDatabase"), patch.object(run_indexer, "install_signal_handlers"), \
                     patch.object(run_indexer, "run_continuous", return_value=returned, side_effect=effect):
                    self.assertEqual(run_indexer.main(["--once"]), 1 if isinstance(outcome, Exception) else outcome)
                factory.assert_called_once()
                decoder.close.assert_called_once_with()

    def test_run_indexer_configuration_failure_after_construction_closes(self):
        decoder = MagicMock()
        with patch.object(run_indexer, "load_transaction_decoder_config"), \
             patch.object(run_indexer, "build_transaction_decoder", return_value=decoder), \
             patch.object(run_indexer, "load_continuous_config", side_effect=ValueError("bad")):
            self.assertEqual(run_indexer.main([]), 1)
        decoder.close.assert_called_once_with()

    def test_index_range_closes_on_success_dry_run_and_failure(self):
        for dry_run, failure in ((False, None), (True, None), (False, RuntimeError("failed"))):
            with self.subTest(dry_run=dry_run, failure=failure):
                decoder = MagicMock()
                selected = SimpleNamespace(client=MagicMock(), finalized_tip=10, probes=[])
                summary = SimpleNamespace(dry_run=dry_run, plan=SimpleNamespace(finalized_tip=10, start_height=1, end_height=1, count=1), processed=[1])
                service = MagicMock(); service.run.return_value = summary; service.run.side_effect = failure
                with patch.object(index_range, "load_transaction_decoder_config"), \
                     patch.object(index_range, "build_transaction_decoder", return_value=decoder) as factory, \
                     patch.object(index_range, "load_config", return_value=IndexerConfig("db", ["rpc"], "chain", 1, 10)), \
                     patch.object(index_range, "select_rpc", return_value=selected), \
                     patch.object(index_range, "PostgresDatabase") as database, \
                     patch.object(index_range, "plan_range", return_value=SimpleNamespace(dry_run=dry_run)), \
                     patch.object(index_range, "IndexerService", return_value=service):
                    self.assertEqual(index_range.main(["--start-height", "1"] + (["--dry-run"] if dry_run else [])), 1 if failure else 0)
                factory.assert_called_once()
                decoder.close.assert_called_once_with()
                if dry_run: database.return_value.get_checkpoint.assert_not_called()
