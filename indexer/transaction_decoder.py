"""Generic supervised JSONL transaction decoder client."""
from __future__ import annotations

import json
import logging
import os
import selectors
import subprocess
import time
from typing import Any, Callable, Protocol, Sequence

from .transaction_summary import MAX_SUMMARY_BYTES, normalize_summary, summary_size_bytes

LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024
SAFE_ERROR_CODES = frozenset({"invalid_base64", "input_too_large", "amino_decode_failed", "invalid_request", "missing_tx_base64"})


class TransactionDecoder(Protocol):
    def decode(self, tx_base64: str, decoded_byte_length: int) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


class _DecoderFailure(Exception):
    def __init__(self, reason: str, category: str = "protocol_failure") -> None:
        self.reason = reason
        self.category = category


class JsonlTransactionDecoder:
    def __init__(
        self,
        command: Sequence[str],
        expected_chain_family: str,
        timeout_seconds: float,
        restart_backoff_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.command = tuple(command)
        self.expected_chain_family = expected_chain_family
        self.timeout_seconds = timeout_seconds
        self.restart_backoff_seconds = restart_backoff_seconds
        self._monotonic = monotonic
        self._popen_factory = popen_factory
        self._process: subprocess.Popen | None = None
        self._response_buffer = bytearray()
        self._request_number = 0
        self._retry_at = 0.0

    def decode(self, tx_base64: str, decoded_byte_length: int) -> dict[str, Any] | None:
        if decoded_byte_length > MAX_DECODED_BYTES or decoded_byte_length < 0 or not isinstance(tx_base64, str):
            return None
        self._request_number += 1
        request_id = f"tx-{self._request_number}"
        request = json.dumps({"id": request_id, "tx_base64": tx_base64}, separators=(",", ":")).encode() + b"\n"
        if len(request) > MAX_REQUEST_BYTES or self._monotonic() < self._retry_at:
            return None
        try:
            process = self._ensure_process()
            deadline = self._monotonic() + self.timeout_seconds
            self._write(process.stdin.fileno(), request, deadline)
            response = self._read_line(process.stdout.fileno(), deadline)
            return self._validate_response(response, request_id)
        except _DecoderFailure as exc:
            self._fail(exc.reason, exc.category)
        except Exception:
            self._fail("process_error", "unavailable")
        return None

    def _ensure_process(self):
        if self._process is not None:
            if self._process.poll() is not None:
                raise _DecoderFailure("process_exit", "unavailable")
            return self._process
        try:
            process = self._popen_factory(
                list(self.command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0, close_fds=True, shell=False,
            )
        except Exception as exc:
            raise _DecoderFailure("start_failed", "unavailable") from exc
        if process.stdin is None or process.stdout is None:
            self._process = process
            raise _DecoderFailure("missing_pipe", "unavailable")
        self._process = process
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        LOGGER.info("transaction_decoder_started family=%s pid=%s", self.expected_chain_family, process.pid)
        return process

    def _wait(self, fd: int, event: int, deadline: float) -> None:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise _DecoderFailure("timeout", "unavailable")
        with selectors.DefaultSelector() as selector:
            selector.register(fd, event)
            if not selector.select(remaining):
                raise _DecoderFailure("timeout", "unavailable")

    def _write(self, fd: int, data: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(data):
            self._wait(fd, selectors.EVENT_WRITE, deadline)
            try:
                written = os.write(fd, data[offset:])
            except BlockingIOError:
                continue
            except (BrokenPipeError, OSError) as exc:
                raise _DecoderFailure("broken_pipe", "unavailable") from exc
            if written <= 0:
                raise _DecoderFailure("broken_pipe", "unavailable")
            offset += written

    def _read_line(self, fd: int, deadline: float) -> bytes:
        while True:
            newline = self._response_buffer.find(b"\n")
            if newline >= 0:
                if newline > MAX_RESPONSE_BYTES:
                    raise _DecoderFailure("response_too_large")
                line = bytes(self._response_buffer[:newline])
                del self._response_buffer[:newline + 1]
                return line
            if len(self._response_buffer) > MAX_RESPONSE_BYTES:
                raise _DecoderFailure("response_too_large")
            self._wait(fd, selectors.EVENT_READ, deadline)
            try:
                chunk = os.read(fd, 8192)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise _DecoderFailure("read_error", "unavailable") from exc
            if not chunk:
                raise _DecoderFailure("eof", "unavailable")
            self._response_buffer.extend(chunk)

    def _validate_response(self, line: bytes, request_id: str) -> dict[str, Any] | None:
        try:
            response = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _DecoderFailure("malformed_json") from exc
        if not isinstance(response, dict):
            raise _DecoderFailure("response_not_object")
        if response.get("protocol_version") != 1:
            raise _DecoderFailure("protocol_version")
        if response.get("id") != request_id:
            raise _DecoderFailure("response_id_mismatch")
        if not isinstance(response.get("ok"), bool):
            raise _DecoderFailure("missing_ok")
        if not response["ok"]:
            code = response.get("error_code")
            if code in SAFE_ERROR_CODES:
                return None
            raise _DecoderFailure("internal_error" if code == "internal_error" else "unexpected_error_code")
        if "summary" not in response:
            raise _DecoderFailure("missing_summary")
        normalized = normalize_summary(response["summary"])
        if (normalized["schema_version"] != 1
                or normalized["chain_family"] != self.expected_chain_family
                or normalized["parse_status"] not in {"parsed", "unsupported"}
                or summary_size_bytes(normalized) > MAX_SUMMARY_BYTES):
            raise _DecoderFailure("invalid_summary")
        return normalized

    def _fail(self, reason: str, category: str) -> None:
        self.close()
        self._retry_at = self._monotonic() + self.restart_backoff_seconds
        LOGGER.warning("transaction_decoder_%s reason=%s family=%s retry_after_seconds=%s", category, reason, self.expected_chain_family, self.restart_backoff_seconds)

    def close(self) -> None:
        process, self._process = self._process, None
        self._response_buffer.clear()
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=0.25)
            else:
                process.wait(timeout=0.25)
        except (OSError, subprocess.SubprocessError):
            pass


def build_transaction_decoder(config) -> TransactionDecoder | None:
    if not config.enabled:
        return None
    return JsonlTransactionDecoder(
        [config.executable_path], config.expected_chain_family,
        config.timeout_seconds, config.restart_backoff_seconds,
    )
