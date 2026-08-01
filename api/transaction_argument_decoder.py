"""Bounded, best-effort argument decoding for Transaction Detail."""

import base64
import binascii
import json
import os
import subprocess
import uuid

from api.config import ApiConfig


MAX_TRANSACTION_BYTES = 4 << 20
MAX_REQUEST_BYTES = 8 << 20
MAX_RESPONSE_BYTES = 72 << 10
MAX_DETAILS_BYTES = 48 << 10
MAX_MESSAGE_ARGUMENTS = 20
MAX_ARGUMENT_VALUES = 16
MAX_ARGUMENT_CHARACTERS = 256


def _validate_message_arguments(value):
    if not isinstance(value, list) or len(value) > MAX_MESSAGE_ARGUMENTS:
        return None
    result = []
    previous_index = -1
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"message_index", "values", "truncated"}:
            return None
        message_index = entry["message_index"]
        values = entry["values"]
        truncated = entry["truncated"]
        if type(message_index) is not int or message_index < 0 or message_index <= previous_index:
            return None
        if not isinstance(values, list) or len(values) > MAX_ARGUMENT_VALUES:
            return None
        if type(truncated) is not bool:
            return None
        if any(
            type(item) is not str
            or len(item) > MAX_ARGUMENT_CHARACTERS
            or (item != "" and not item.isprintable())
            for item in values
        ):
            return None
        previous_index = message_index
        result.append({"message_index": message_index, "values": values, "truncated": truncated})
    return result


def decode_transaction_arguments(
    raw_base64: str,
    decoded_byte_length: int,
    config: ApiConfig,
):
    """Return validated MsgCall argument details, or None on every failure."""
    if type(raw_base64) is not str or not raw_base64 or type(decoded_byte_length) is not int:
        return None
    if not 0 <= decoded_byte_length <= MAX_TRANSACTION_BYTES:
        return None
    try:
        raw = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != decoded_byte_length:
        return None

    request_id = f"detail-{uuid.uuid4().hex}"
    request = json.dumps(
        {"id": request_id, "tx_base64": raw_base64, "include_arguments": True},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if len(request) > MAX_REQUEST_BYTES:
        return None
    child_environment = {
        name: os.environ[name]
        for name in ("PATH", "LANG", "LC_ALL")
        if name in os.environ
    }
    try:
        completed = subprocess.run(
            [config.transaction_detail_decoder_path],
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=config.transaction_detail_decoder_timeout_seconds,
            check=False,
            shell=False,
            env=child_environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout or len(completed.stdout) > MAX_RESPONSE_BYTES:
        return None
    try:
        response = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(response, dict)
        or response.get("protocol_version") != 1
        or response.get("id") != request_id
        or response.get("ok") is not True
        or not isinstance(response.get("details"), dict)
        or set(response["details"]) != {"message_arguments"}
        or len(json.dumps(response["details"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_DETAILS_BYTES
    ):
        return None
    return _validate_message_arguments(response["details"]["message_arguments"])
