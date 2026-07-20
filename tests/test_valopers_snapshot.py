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


def address_number(value: str) -> int:
    alphabet = "023456789acdefghjklmnpqrstuvwxyz"
    number = 0
    multiplier = 1
    for character in value[2:]:
        number += alphabet.index(character) * multiplier
        multiplier *= len(alphabet)
    return number


def list_render(start: int, count: int) -> str:
    if not count:
        return "Valopers\n\nNo valopers to display."
    return "\n".join(
        f" * [Node {number}](/r/gnops/valopers:{address(number)}) - "
        f"[profile](/r/demo/profile:u/{address(number)})"
        for number in range(start, start + count)
    )


def list_render_numbers(numbers) -> str:
    return "\n".join(
        f" * [Node {number}](/r/gnops/valopers:{address(number)}) - "
        f"[profile](/r/demo/profile:u/{address(number)})"
        for number in numbers
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
    def __init__(self, pages, detail_overrides=None, fail_detail=None, fail_pages=None):
        self.pages = pages
        self.detail_overrides = detail_overrides or {}
        self.fail_detail = fail_detail
        self.fail_pages = set(fail_pages or ())
        self.calls = []

    def get(self, method, **params):
        raw = base64.b64decode(json.loads(params["data"])).decode()
        self.calls.append((raw, params["height"]))
        suffix = raw.split(":", 1)[1]
        if suffix.startswith("g1"):
            number = address_number(suffix)
            if number == self.fail_detail:
                raise RpcError("transport failed at https://secret.example/token")
            text = self.detail_overrides.get(number, detail_render(number))
        elif suffix.startswith("?page="):
            page_number = int(suffix.removeprefix("?page="))
            if page_number in self.fail_pages:
                raise RpcError("list transport failed")
            text = self.pages[page_number - 1]
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

    def test_full_root_requests_page_two_at_same_height(self):
        client = FakeClient([list_render(0, 50), list_render(50, 1)])
        collect_valopers_snapshot(client, 456)
        self.assertEqual(client.calls[1], ("gno.land/r/gnops/valopers:?page=2", 456))

    def test_page_numbers_are_sequential_and_list_height_is_pinned(self):
        client = FakeClient([
            list_render(0, 50), list_render(50, 50), list_render(100, 1)
        ])
        collect_valopers_snapshot(client, 789)
        self.assertEqual(
            client.calls[:3],
            [("gno.land/r/gnops/valopers:", 789),
             ("gno.land/r/gnops/valopers:?page=2", 789),
             ("gno.land/r/gnops/valopers:?page=3", 789)],
        )

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

    def test_twenty_full_pages_and_empty_terminal_page_succeed(self):
        pages = [list_render(page * 50, 50) for page in range(MAX_VALOPERS_PAGES)]
        pages.append(list_render(0, 0))
        client = FakeClient(pages)
        snapshot = collect_valopers_snapshot(client, 1)
        self.assertEqual(snapshot.page_count, 20)
        self.assertEqual(len(snapshot.profiles), 1000)
        self.assertEqual(client.calls[20][0], "gno.land/r/gnops/valopers:?page=21")
        self.assertTrue(all(data.startswith("gno.land/r/gnops/valopers:g1") for data, _ in client.calls[21:]))
        self.assertNotIn("gno.land/r/gnops/valopers:?page=22", [data for data, _ in client.calls])

    def test_nonempty_terminal_page_fails_before_details(self):
        pages = [list_render(page * 50, 50) for page in range(MAX_VALOPERS_PAGES)]
        client = FakeClient(pages + [list_render(1000, 1)])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 21)
        self.assertNotIn("?page=22", [data for data, _ in client.calls])

    def test_malformed_terminal_page_fails_before_details(self):
        pages = [list_render(page * 50, 50) for page in range(MAX_VALOPERS_PAGES)]
        client = FakeClient(pages + ["malformed"])
        with self.assertRaises(ValueError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 21)

    def test_terminal_page_transport_failure_fails_before_details(self):
        pages = [list_render(page * 50, 50) for page in range(MAX_VALOPERS_PAGES)]
        client = FakeClient(pages + [list_render(0, 0)], fail_pages={21})
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 21)

    def test_explicit_profile_guard_fails_closed(self):
        client = FakeClient([list_render(0, 50), list_render(50, 1)])
        with patch("indexer.valopers_snapshot.MAX_VALOPERS_PROFILES", 50):
            with self.assertRaises(RpcError):
                collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 2)

    def test_malformed_or_failed_page_two_returns_no_partial_snapshot(self):
        for client, error in (
            (FakeClient([list_render(0, 50), "malformed"]), ValueError),
            (FakeClient([list_render(0, 50), list_render(50, 1)], fail_pages={2}), RpcError),
        ):
            with self.subTest(error=error):
                with self.assertRaises(error):
                    collect_valopers_snapshot(client, 8)
                self.assertEqual(len(client.calls), 2)

    def test_same_operator_set_in_different_order_fails(self):
        first = list(range(50))
        client = FakeClient([list_render_numbers(first), list_render_numbers(reversed(first))])
        with self.assertRaises(RpcError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 2)

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

    def test_details_start_after_pagination_and_match_list_order_and_height(self):
        client = FakeClient([list_render(0, 50), list_render(50, 2)])
        snapshot = collect_valopers_snapshot(client, 222)
        detail_calls = client.calls[2:]
        self.assertEqual(len(detail_calls), 52)
        self.assertEqual(
            [data for data, _ in detail_calls],
            [f"gno.land/r/gnops/valopers:{address(number)}" for number in range(52)],
        )
        self.assertEqual([height for _, height in detail_calls], [222] * 52)
        self.assertEqual(len(snapshot.profiles), 52)

    def test_malformed_detail_stops_later_detail_fetches(self):
        client = FakeClient([list_render(0, 3)], {1: "malformed detail"})
        with self.assertRaises(ValueError):
            collect_valopers_snapshot(client, 1)
        self.assertEqual(len(client.calls), 3)

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
        credential_url = "https://user:secret@example.invalid/rpc?token=private"

        def noisy_selection(*_args, **_kwargs):
            print(credential_url)
            print(credential_url, file=sys.stderr)
            return selected_client, {}

        select.side_effect = noisy_selection
        profile = collect_valopers_snapshot(FakeClient([list_render(0, 1)]), 44).profiles[0]
        collect.return_value = ValopersSnapshot(44, 1, (profile,))
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("source_height=44 pages=1 profiles=1", stdout.getvalue())
        combined = stdout.getvalue() + stderr.getvalue()
        for secret in ("user", "secret", "token=private", credential_url):
            self.assertNotIn(secret, combined)
        self.assertNotIn("description", combined)
        self.assertNotIn("gpub", combined)
        self.assertNotIn("ValoperProfile", combined)
        self.assertLess(len(stdout.getvalue()), 256)
        collect.assert_called_once_with(selected_client, 44)

    @patch("scripts.probe_valopers_snapshot.collect_valopers_snapshot", return_value=ValopersSnapshot(44, 0, ()))
    @patch("scripts.probe_valopers_snapshot.parse_status", return_value={"latest_height": 44})
    @patch("scripts.probe_valopers_snapshot.select_healthy_rpc", return_value=(object(), {}))
    def test_empty_snapshot_output_is_bounded(self, _select, _status, _collect):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from scripts.probe_valopers_snapshot import main
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("pages=0 profiles=0", stdout.getvalue())
        self.assertLess(len(stdout.getvalue()), 256)

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

    @patch("scripts.probe_valopers_snapshot.collect_valopers_snapshot", side_effect=RpcError("https://user:secret@example.invalid/rpc?token=private"))
    @patch("scripts.probe_valopers_snapshot.parse_status", return_value={"latest_height": 44})
    @patch("scripts.probe_valopers_snapshot.select_healthy_rpc", return_value=(object(), {}))
    def test_collection_exception_url_is_replaced(self, _select, _status, _collect):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from scripts.probe_valopers_snapshot import main
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "Valopers snapshot failed: collection did not complete\n")


if __name__ == "__main__":
    unittest.main()
