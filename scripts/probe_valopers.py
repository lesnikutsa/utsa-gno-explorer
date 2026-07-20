#!/usr/bin/env python3
"""Run bounded, read-only Valopers vm/qrender probes."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from indexer.valopers_source import (
    ValopersRenderResult,
    build_detail_render_data,
    build_page_render_data,
    build_root_render_data,
    fetch_render,
)
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
    return parser


def requested_renders(args: argparse.Namespace) -> list[tuple[str, str]]:
    renders = [("root", build_root_render_data())]
    if args.page_query is not None:
        renders.append(("page", build_page_render_data(args.page_query)))
    if args.operator_address is not None:
        renders.append(("detail", build_detail_render_data(args.operator_address)))
    return renders


def format_result(result: ValopersRenderResult) -> str:
    return (
        f"kind={result.query_kind} source_height={result.source_height} "
        f"response_height={result.response_height} decoded_bytes={result.decoded_byte_count} "
        f"sha256={result.sha256} preview={result.preview!r}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        renders = requested_renders(args)
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
    except RpcError as exc:
        print(f"Valopers probe failed: {exc}", file=sys.stderr)
        return 1

    for result in results:
        print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
