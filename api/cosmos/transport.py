"""Bounded read-only JSON transport."""

import asyncio
import json
from urllib.parse import urlsplit

import httpx

from .errors import MalformedUpstreamResponse, RejectedEndpoint


class JsonTransport:
    def __init__(self, *, timeout: float, max_response_bytes: int, client=None, transport=None):
        self._owned = client is None
        self._timeout_seconds = timeout
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0), read=timeout,
                                      write=timeout, pool=timeout)
        self._client = client or httpx.AsyncClient(
            transport=transport,
            timeout=self._timeout,
            follow_redirects=False,
        )
        self._max_response_bytes = max_response_bytes

    async def get_object(self, base_url: str, path: str) -> dict:
        parsed = urlsplit(path)
        if not path.startswith("/") or parsed.scheme or parsed.netloc or parsed.fragment or len(path) > 512:
            raise ValueError("adapter path must be relative")
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._client.stream("GET", base_url.rstrip("/") + path,
                                               timeout=self._timeout) as response:
                    if not 200 <= response.status_code < 300:
                        raise RejectedEndpoint("http_status")
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise MalformedUpstreamResponse("upstream response is too large")
                        chunks.append(chunk)
                    body = b"".join(chunks)
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RejectedEndpoint("transport_error") from exc
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedUpstreamResponse("upstream response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise MalformedUpstreamResponse("upstream JSON is not an object")
        return payload

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.aclose()
