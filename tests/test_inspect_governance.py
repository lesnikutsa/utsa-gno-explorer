import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from governance.gno import GovernanceDiscovery, GovernanceSource
from scripts.inspect_governance import main


class InspectGovernanceTests(unittest.TestCase):
    @patch("scripts.inspect_governance.discover_governance")
    @patch("scripts.inspect_governance.select_rpc")
    @patch("scripts.inspect_governance.configured_rpc_urls", return_value=["https://rpc"])
    def test_json_stdout_contains_only_json(self, _urls, select, discover):
        select.return_value.client.base_url = "https://rpc/"
        select.return_value.latest_height = 42
        discover.return_value = GovernanceDiscovery(GovernanceSource("topaz-1", "https://rpc", 42, "gno.land/r/gov/dao"), True, 1, ())
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--json", "--include-raw"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["proposal_count"], 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(discover.call_args.kwargs["capture_raw"])

    @patch("scripts.inspect_governance.discover_governance")
    @patch("scripts.inspect_governance.select_rpc")
    @patch("scripts.inspect_governance.configured_rpc_urls", return_value=["https://rpc"])
    def test_raw_directory_uses_streaming_sink_without_capture(self, _urls, select, discover):
        select.return_value.client.base_url = "https://rpc/"
        select.return_value.latest_height = 42
        source = GovernanceSource("topaz-1", "https://rpc", 42, "gno.land/r/gov/dao")

        def run_discovery(*args, **kwargs):
            kwargs["raw_sink"]("proposal/20/votes", "No one voted yet.")
            return GovernanceDiscovery(source, True, 0, ())

        discover.side_effect = run_discovery
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--raw-dir", directory]), 0)
            self.assertEqual((Path(directory) / "proposal_20_votes.md").read_text(), "No one voted yet.")
        self.assertFalse(discover.call_args.kwargs["capture_raw"])

    def test_invalid_configuration_does_not_echo_environment(self):
        stderr = io.StringIO()
        with patch.dict("os.environ", {"DATABASE_URL": "secret-value"}), redirect_stderr(stderr):
            self.assertEqual(main(["--realm", "bad:realm"]), 2)
        self.assertNotIn("secret-value", stderr.getvalue())

    @patch("scripts.inspect_governance.select_rpc")
    def test_invalid_discovery_limits_exit_before_rpc_or_raw_directory(self, select):
        cases = (
            ("--max-pages", "0"),
            ("--max-pages", "101"),
            ("--max-proposals", "0"),
            ("--max-proposals", "1001"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (flag, value) in enumerate(cases):
                raw_directory = Path(directory) / str(index)
                stderr = io.StringIO()
                with patch.dict("os.environ", {"DATABASE_URL": "database-secret"}), redirect_stderr(stderr):
                    self.assertEqual(main([flag, value, "--raw-dir", str(raw_directory)]), 2)
                self.assertIn("invalid governance configuration", stderr.getvalue())
                self.assertNotIn("database-secret", stderr.getvalue())
                self.assertFalse(raw_directory.exists())
        select.assert_not_called()


if __name__ == "__main__": unittest.main()
