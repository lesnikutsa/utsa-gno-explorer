"""Tendermint-compatible ``/net_info`` adapter."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import requests


@dataclass(frozen=True)
class PeerIdentity:
    node_id: str
    ip: str


def _node_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 255 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in normalized):
        return None
    return normalized


def _public_ip(address: str) -> str | None:
    value = address.strip()
    if value.startswith(("tcp://", "p2p://")):
        value = value.split("://", 1)[1]
    # net_address commonly uses node-id@host:port.
    if "@" in value:
        value = value.rsplit("@", 1)[1]
        if value.startswith(("tcp://", "p2p://")):
            value = value.split("://", 1)[1]
    try:
        parsed = urlsplit("//" + value)
        host = parsed.hostname
        if not host:
            return None
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return None
        ip = ipaddress.ip_address(host)
    except (ValueError, TypeError):
        return None
    if (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
        return None
    return ip.compressed


def parse_peer(peer: dict) -> PeerIdentity | None:
    info = peer.get("node_info") if isinstance(peer.get("node_info"), dict) else {}
    net_address = info.get("net_address")
    fallback_id = next((_node_id(v) for v in (info.get("id"), peer.get("node_id"), peer.get("id")) if _node_id(v)), None)
    if isinstance(net_address, str):
        address_value = net_address
        embedded_id = None
        without_scheme = address_value.split("://", 1)[1] if address_value.startswith(("tcp://", "p2p://")) else address_value
        if "@" in without_scheme:
            embedded, address = without_scheme.rsplit("@", 1)
            embedded_id = _node_id(embedded)
            address_value = address
        ip = _public_ip(net_address)
        if embedded_id and ip:
            return PeerIdentity(embedded_id, ip)
        ip = _public_ip(address_value)
        if fallback_id and ip:
            return PeerIdentity(fallback_id, ip)
    node_id = fallback_id
    address = next((v for v in (info.get("listen_addr"), peer.get("remote_ip"), peer.get("ip"), peer.get("remote_addr")) if isinstance(v, str) and v.strip()), None)
    ip = _public_ip(address) if address else None
    return PeerIdentity(node_id, ip) if node_id and ip else None


def parse_net_info(payload: object) -> tuple[int, list[PeerIdentity]]:
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("rpc_error" if isinstance(payload, dict) and payload.get("error") else "malformed_net_info")
    result = payload.get("result")
    peers = result.get("peers") if isinstance(result, dict) else None
    if not isinstance(peers, list):
        raise ValueError("malformed_net_info")
    identities: dict[str, PeerIdentity] = {}
    for peer in peers:
        identity = parse_peer(peer) if isinstance(peer, dict) else None
        if identity and identity.node_id not in identities:
            identities[identity.node_id] = identity
    try:
        reported = int(result.get("n_peers", len(peers)))
    except (ValueError, TypeError):
        reported = len(peers)
    return max(reported, 0), list(identities.values())


def fetch_net_info(base_url: str, timeout: int) -> tuple[int, list[PeerIdentity]]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("request_error")
    path = parsed.path.rstrip("/") + "/net_info"
    url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise ValueError("timeout") from exc
    except requests.RequestException as exc:
        raise ValueError("request_error") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("invalid_json") from exc
    return parse_net_info(payload)
