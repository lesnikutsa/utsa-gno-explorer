import base64
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from indexer.valopers_snapshot import (
    MAX_VALOPERS_PAGES,
    VALOPERS_PAGE_SIZE,
    ValopersSnapshot,
    collect_valopers_snapshot,
)
from scripts.inspect_rpc import RpcError


def address(number: int) -> str:
    alphabet = "023456789acdefghjklmnpqrstuvwxyz"
    value = number
    chars = []
    for _ in range(38):
        chars.append(alphabet[value % len(alphabet)])
        value //= len(alphabet)
    return "g1" + "".join(chars)


def list_render(start: int, count: int) -> str:
    if not count:
        return "Valopers\n\nNo valopers to display."
    return "\n".join(
        f" * [Node {number}](/r/gnops/valopers:{address(number)}) - "
        f"[profile](/r/demo/profile:u/{address(number)})"
        for number in range(start, start + count)
    )


def detail_render(number: int, *, operator=None, moniker=None, signing=None, pubkey=None) -> str:
    operator = operator or address(number)
    signing = signing or address(10_000 + number)
    pubkey = pubkey or "gpub1" + address(number)[2:] + ("2" * 53)
    return (
        f"Valoper's details:\n## {moniker or f'Node {number}'}\nsecret-description-{number}\n\n"
        f"- Operator Address: {operator}\n- Signing Address: {signing}\n"
        f"- Signing PubKey: {pubkey}\n- Server Type: cloud\n\n"
        f"[Profile link](/r/demo/profile:u/{operator})\n"
    )


class FakeClient:
    def __init__(self, pages, detail_overrides=None, fail_detail=None):
        self.pages = pages
        self.detail_overrides = detail_overrides or {}
        self.fail_detail = fail_detail
        self.calls = []

    def get(self, method, **params):
        raw = base64.b64decode(json.loads(params["data"])).decode()
        self.calls.append((raw, params["height"]))
        suffix = raw.split(":", 1)[1]
        if suffix.startswith("g1"):
            number = next(i for i in range(20_000) if address(i) == suffix)
            if number == self.fail_detail:
                raise RpcError("transport failed at https://secret.example/token")
            text = self.detail_overrides.get(number, detail_render(number))
        elif suffix.startswith("?page="):
            text = self.pages[int(suffix.removeprefix("?page=")) - 1]
        else:
            text = self.pages[0]
        encoded = base64.b64encode(text.encode()).decode()
        return {"result": {"response": {"Height": str(params["height"]), "ResponseBase": {"Error": None, "Data": encoded}}}}


class SnapshotTests(unittest.TestCase):
    def test_empty_root(self):
        client = FakeClient([list_render(0, 0)])
        snapshot = collect_valopers_snapshot(client, 123)
        self.assertEqual(snapshot, ValopersSnapshot(123, 0, ()))
        self.assertEqual(len(client.calls), 1)

    def test_short_root_fetches_all_details_in_order_at_one_height(self):
        client = FakeClient([list_render(0, 3)])
        snapshot = collect_valopers_snapshot(client, 123)
        self.assertEqual(snapshot.page_count, 1)
        self.assertEqual([p.operator_address for p in snapshot.profiles], [address(i) for i in range(3)])
        self.assertEqual([height for _, height in client.calls], [123] * 4)
        self.assertNotIn("?page=2", [data for data, _ in client.calls])

    def test_full_then_short_page(self):
        client = FakeClient([list_render(0, 50), list_render(50, 2)])
        snapshot = collect_valopers_snapshot(client, 9)
        self.assertEqual((snapshot.page_count, len(snapshot.profiles)), (2, 52))
        self.assertEqual(client.calls[1][0].split(":", 1)[1], "?page=2")

    def test_exact_multiple_requires_empty_terminal_page(self):
        client = FakeClient([list_render(0, 50), list_render(50, 50), list_render(0, 0)])
        snapshot = collect_valopers_snapshot(client, 9)
        self.assertEqual((snapshot.page_count, len(snapshot.profiles)), (2, 100))
        self.assertEqual([call[0].split(":", 1)[1] for call in client.calls[:3]], ["", "?page=2", "?page=3"])

    def test_oversized_page_fails_before_details(self):
        client = FakeClient([list_render(0, VALOPERS_PAGE_SIZE + 1)])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 1)

    def test_repeated_page_fails_before_details(self):
        page = list_render(0, 50)
        client = FakeClient([page, page])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 2)

    def test_duplicate_operator_across_pages_fails(self):
        client = FakeClient([list_render(0, 50), list_render(49, 2)])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)

    def test_maximum_page_bound_fails_without_unbounded_request(self):
        client = FakeClient([list_render(page * 50, 50) for page in range(MAX_VALOPERS_PAGES)])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), MAX_VALOPERS_PAGES)

    def test_detail_identity_mismatches_fail(self):
        for override in (
            detail_render(0, operator=address(99)),
            detail_render(0, moniker="Wrong Node"),
        ):
            with self.subTest(override=override):
                with self.assertRaises(RpcError):
                    collect_valopers_snapshot(FakeClient([list_render(0, 1)], {0: override}), 1)

    def test_duplicate_signing_identity_fails(self):
        common_signing = address(15_000)
        common_pubkey = "gpub1" + "2" * 91
        cases = (
            {0: detail_render(0, signing=common_signing), 1: detail_render(1, signing=common_signing)},
            {0: detail_render(0, pubkey=common_pubkey), 1: detail_render(1, pubkey=common_pubkey)},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(RpcError):
                    collect_valopers_snapshot(FakeClient([list_render(0, 2)], overrides), 1)

    def test_final_detail_transport_failure_returns_no_snapshot(self):
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(FakeClient([list_render(0, 2)], fail_detail=1), 1)

    def test_immutable_and_safe_bounded_repr(self):
        snapshot = collect_valopers_snapshot(FakeClient([list_render(0, 10)]), 1)
        self.assertIsInstance(snapshot.profiles, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.page_count = 7
        with self.assertRaises(FrozenInstanceError):
            snapshot.profiles[0].description = "changed"
        representation = repr(snapshot)
        self.assertNotIn("secret-description", representation)
        self.assertNotIn("gpub", representation)
        self.assertLess(len(representation), 100)

    def test_invalid_height_fails_without_request(self):
        client = FakeClient([list_render(0, 0)])
        for height in (0, -1, True, "1"):
            with self.assertRaises(RpcError):
                collect_valopers_snapshot(client, height)
        self.assertFalse(client.calls)


class SnapshotCliTests(unittest.TestCase):
    def test_help_executes_directly(self):
        result = subprocess.run(
            [sys.executable, "scripts/probe_valopers_snapshot.py", "--help"],
            cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("bounded Valopers", result.stdout)

    @patch("scripts.probe_valopers_snapshot.collect_valopers_snapshot")
    @patch("scripts.probe_valopers_snapshot.parse_status", return_value={"latest_height": 44})
    @patch("scripts.probe_valopers_snapshot.select_healthy_rpc")
    def test_selection_output_is_suppressed_and_summary_is_safe(self, select, _status, collect):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from scripts.probe_valopers_snapshot import main
        selected_client = object()
        select.side_effect = lambda *a, **k: (print("https://user:pass@rpc/?token=secret") or selected_client, {})
        profile = collect_valopers_snapshot(FakeClient([list_render(0, 1)]), 44).profiles[0]
        collect.return_value = ValopersSnapshot(44, 1, (profile,))
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("source_height=44 pages=1 profiles=1", stdout.getvalue())
        self.assertNotIn("pass", stdout.getvalue())
        self.assertNotIn("description", stdout.getvalue())
        self.assertNotIn("gpub", stdout.getvalue())
        collect.assert_called_once_with(selected_client, 44)

    @patch("scripts.probe_valopers_snapshot.select_healthy_rpc", side_effect=RpcError("https://secret/whole-response"))
    def test_failure_is_generic(self, _select):
        from contextlib import redirect_stderr
        from io import StringIO
        from scripts.probe_valopers_snapshot import main
        stderr = StringIO()
        with redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "Valopers snapshot failed: collection did not complete\n")


if __name__ == "__main__":
    unittest.main()
