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

    async def get_object(self, base_url: str, path: str, *, accept_error_payload: bool = False) -> dict:
        parsed = urlsplit(path)
        if not path.startswith("/") or parsed.scheme or parsed.netloc or parsed.fragment or len(path) > 512:
            raise ValueError("adapter path must be relative")
        transport_failed = False
        async def read_response() -> bytes:
            async with self._client.stream("GET", base_url.rstrip("/") + path,
                                           timeout=self._timeout) as response:
                if not 200 <= response.status_code < 300 and not accept_error_payload:
                    raise RejectedEndpoint("http_status")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_response_bytes:
                        raise MalformedUpstreamResponse("upstream response is too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        try:
            body = await asyncio.wait_for(read_response(), timeout=self._timeout_seconds)
        except (asyncio.TimeoutError, httpx.RequestError):
            transport_failed = True
        if transport_failed:
            # Raise outside the handler so secret-bearing transport exceptions are
            # not retained as __context__ on the safe adapter error.
            raise RejectedEndpoint("transport_error")
        malformed_json = False
        try:
            payload = json.loads(
                body,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            malformed_json = True
        if malformed_json:
            raise MalformedUpstreamResponse("upstream response is not valid JSON")
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
