#!/usr/bin/env python3
"""Run bounded, read-only Valopers vm/qrender probes."""
from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indexer.valopers_source import (
    ValopersRenderResult,
    build_detail_render_data,
    build_page_render_data,
    build_root_render_data,
    fetch_render,
)
from indexer.valopers_parser import parse_valoper_detail, parse_valopers_list
from scripts.inspect_rpc import (
    RpcError,
    configured_chain_id,
    configured_rpc_urls,
    parse_status,
    select_healthy_rpc,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe bounded Valopers qrender responses")
    parser.add_argument("--page-query", help="explicit pagination query, for example ?page=2")
    parser.add_argument("--operator-address", help="explicit lowercase g1 operator address")
    parser.add_argument("--parse", action="store_true", help="parse and summarize each render")
    return parser


def requested_renders(args: argparse.Namespace) -> list[tuple[str, str]]:
    renders = []
    if args.page_query is not None:
        renders.append(("page", build_page_render_data(args.page_query)))
    if args.operator_address is not None:
        renders.append(("detail", build_detail_render_data(args.operator_address)))
    return renders or [("root", build_root_render_data())]


def format_result(result: ValopersRenderResult) -> str:
    response_height = result.response_height if result.response_height is not None else "unreported"
    return (
        f"kind={result.query_kind} source_height={result.source_height} "
        f"response_height={response_height} decoded_bytes={result.decoded_byte_count} "
        f"sha256={result.sha256} preview={result.preview!r}"
    )


def format_parsed_result(result: ValopersRenderResult) -> str:
    if result.query_kind == "detail":
        profile = parse_valoper_detail(result.decoded_text)
        return (
            f"parsed_kind=detail moniker={profile.moniker!r} "
            f"operator_address={profile.operator_address} signing_address={profile.signing_address} "
            f"server_type={profile.server_type} description_chars={len(profile.description)}"
        )
    entries = parse_valopers_list(result.decoded_text)
    first = entries[0].moniker if entries else ""
    last = entries[-1].moniker if entries else ""
    return f"parsed_kind=list entries={len(entries)} first_moniker={first!r} last_moniker={last!r}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        renders = requested_renders(args)
        # inspect_rpc intentionally reports endpoint URLs; suppress that diagnostic
        # output here because configured URLs may contain credentials or tokens.
        with redirect_stdout(io.StringIO()):
            client, status_payload = select_healthy_rpc(
                configured_rpc_urls(), expected_chain_id=configured_chain_id()
            )
        source_height = parse_status(status_payload)["latest_height"]
        if not isinstance(source_height, int) or source_height < 1:
            raise RpcError("Selected RPC status has no valid committed latest height")
        results = [
            fetch_render(client, render_data, query_kind, source_height)
            for query_kind, render_data in renders
        ]
    except (RpcError, TypeError, ValueError) as exc:
        print(f"Valopers probe failed: {exc}", file=sys.stderr)
        return 1

    for result in results:
        if args.parse:
            try:
                parsed_summary = format_parsed_result(result)
            except (TypeError, ValueError):
                print("Valopers probe failed: render did not match the parser contract", file=sys.stderr)
                return 1
            print(format_result(result))
            print(parsed_summary)
        else:
            print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
