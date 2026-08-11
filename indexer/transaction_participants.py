"""Extract bounded account participation from normalized transaction summaries."""
from __future__ import annotations

from typing import Any, NamedTuple

from api.network_profile import gno_profile, validate_account_address
from .transaction_summary import MAX_MESSAGES


class TransactionParticipant(NamedTuple):
    message_index: int
    role: str
    address: str


def extract_transaction_participants(summary: Any) -> list[TransactionParticipant]:
    """Return deterministic, unique sender/recipient rows or an empty safe fallback."""
    try:
        if not isinstance(summary, dict) or summary.get("parse_status") != "parsed":
            return []
        messages = summary.get("messages")
        if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
            return []
        profile = gno_profile("")
        found: set[TransactionParticipant] = set()
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                return []
            for role in ("sender", "recipient"):
                address = message.get(role)
                if isinstance(address, str) and validate_account_address(address, profile):
                    found.add(TransactionParticipant(message_index, role, address))
        return sorted(found)
    except (TypeError, ValueError):
        return []
