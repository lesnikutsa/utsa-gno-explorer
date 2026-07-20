"""Bounded collection of a complete, in-memory Valopers registry snapshot."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from indexer.valopers_parser import ValoperListEntry, ValoperProfile, parse_valoper_detail, parse_valopers_list
from indexer.valopers_source import (
    ValopersRenderResult,
    build_detail_render_data,
    build_page_render_data,
    build_qrender_params,
    build_root_render_data,
    decode_qrender_response,
)
from scripts.inspect_rpc import GnoRpcClient, RpcError

VALOPERS_PAGE_SIZE = 50
MAX_VALOPERS_PAGES = 20
MAX_VALOPERS_PROFILES = 1000
MAX_LIST_REQUESTS = MAX_VALOPERS_PAGES + 1
VALOPERS_FETCH_ATTEMPTS = 3
VALOPERS_RETRY_DELAY_SECONDS = 0.25


@dataclass(frozen=True)
class ValopersSnapshot:
    """Metadata and profiles from one complete, pinned-height collection."""

    source_height: int
    page_count: int
    profiles: tuple[ValoperProfile, ...] = field(repr=False)


def _fetch_with_retry(
    client: GnoRpcClient, render_data: str, query_kind: str, source_height: int
) -> ValopersRenderResult:
    """Retry only transport fetches, preserving the client, query, and height."""
    params = build_qrender_params(render_data, source_height)
    for attempt in range(VALOPERS_FETCH_ATTEMPTS):
        try:
            payload = client.get("abci_query", **params)
        except RpcError as exc:
            if attempt + 1 == VALOPERS_FETCH_ATTEMPTS:
                raise RpcError("Valopers qrender request failed after bounded retries") from exc
            time.sleep(VALOPERS_RETRY_DELAY_SECONDS)
            continue
        return decode_qrender_response(payload, query_kind, source_height)
    raise AssertionError("unreachable")  # pragma: no cover


def _collect_list(client: GnoRpcClient, source_height: int) -> tuple[list[ValoperListEntry], int]:
    entries: list[ValoperListEntry] = []
    seen_operators: set[str] = set()
    seen_sequences: set[tuple[str, ...]] = set()
    seen_sets: set[frozenset[str]] = set()

    for page_number in range(1, MAX_LIST_REQUESTS + 1):
        render_data = (
            build_root_render_data()
            if page_number == 1
            else build_page_render_data(f"?page={page_number}")
        )
        rendered = _fetch_with_retry(
            client, render_data, "root" if page_number == 1 else "page", source_height
        )
        page = parse_valopers_list(rendered.decoded_text)
        if len(page) > VALOPERS_PAGE_SIZE:
            raise RpcError("Valopers page exceeds the page-size limit")
        if not page:
            return entries, 0 if page_number == 1 else page_number - 1
        if page_number > MAX_VALOPERS_PAGES:
            raise RpcError("Valopers registry exceeds the page limit")

        operators = tuple(entry.operator_address for entry in page)
        operator_set = frozenset(operators)
        if operators in seen_sequences or operator_set in seen_sets:
            raise RpcError("Valopers list page repeats earlier contents")
        if seen_operators.intersection(operator_set):
            raise RpcError("Duplicate Valoper operator address across pages")
        seen_sequences.add(operators)
        seen_sets.add(operator_set)
        seen_operators.update(operator_set)
        entries.extend(page)
        if len(entries) > MAX_VALOPERS_PROFILES:
            raise RpcError("Valopers registry exceeds the profile limit")
        if len(page) < VALOPERS_PAGE_SIZE:
            return entries, page_number
    raise RpcError("Valopers registry pagination did not terminate")  # pragma: no cover


def collect_valopers_snapshot(client: GnoRpcClient, source_height: int) -> ValopersSnapshot:
    """Collect and validate every list and detail render at ``source_height``."""
    if not isinstance(source_height, int) or isinstance(source_height, bool) or source_height < 1:
        raise RpcError("Pinned source height must be a positive integer")

    entries, page_count = _collect_list(client, source_height)
    profiles: list[ValoperProfile] = []
    signing_addresses: set[str] = set()
    signing_pubkeys: set[str] = set()
    for entry in entries:
        rendered = _fetch_with_retry(
            client,
            build_detail_render_data(entry.operator_address),
            "detail",
            source_height,
        )
        profile = parse_valoper_detail(rendered.decoded_text)
        if profile.operator_address != entry.operator_address:
            raise RpcError("Valoper detail operator does not match its list entry")
        if profile.moniker != entry.moniker:
            raise RpcError("Valoper detail moniker does not match its list entry")
        if profile.signing_address in signing_addresses:
            raise RpcError("Duplicate Valoper signing address")
        if profile.signing_pubkey in signing_pubkeys:
            raise RpcError("Duplicate Valoper signing public key")
        signing_addresses.add(profile.signing_address)
        signing_pubkeys.add(profile.signing_pubkey)
        profiles.append(profile)

    if len(profiles) != len(entries):
        raise RpcError("Valopers profile count does not match the list")
    return ValopersSnapshot(source_height, page_count, tuple(profiles))
