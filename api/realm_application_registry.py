"""Immutable, version-controlled metadata for manually curated Realm namespaces."""
from types import MappingProxyType
from typing import Any, Mapping

from indexer.realm_catalog import namespace_key

_MAX_TEXT = 256
_RAW_ENTRIES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("gnoswap", {
        "display_name": "GnoSwap",
        "category": "DeFi",
        "description": None,
        "website": None,
        "metadata_source": "curated_registry",
    }),
)


def _validated_registry(entries: tuple[tuple[str, dict[str, Any]], ...]) -> Mapping[str, Mapping[str, Any]]:
    keys = [key for key, _ in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate curated namespace")
    for key, metadata in entries:
        if namespace_key(f"gno.land/r/{key}") != key:
            raise ValueError("invalid curated namespace")
        if set(metadata) != {"display_name", "category", "description", "website", "metadata_source"}:
            raise ValueError("invalid curated metadata fields")
        for field in ("display_name", "category"):
            value = metadata[field]
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > _MAX_TEXT or not value.isprintable():
                raise ValueError("invalid curated metadata text")
        for field in ("description", "website"):
            value = metadata[field]
            if value is not None and (not isinstance(value, str) or not value or value != value.strip() or len(value) > _MAX_TEXT or not value.isprintable()):
                raise ValueError("invalid optional curated metadata text")
        if metadata["website"] is not None and not metadata["website"].startswith("https://"):
            raise ValueError("curated website must use HTTPS")
        if metadata["metadata_source"] != "curated_registry":
            raise ValueError("invalid curated metadata source")
    return MappingProxyType({key: MappingProxyType(dict(value)) for key, value in entries})


REALM_APPLICATION_REGISTRY = _validated_registry(_RAW_ENTRIES)
CURATED_NAMESPACE_KEYS = tuple(sorted(REALM_APPLICATION_REGISTRY))
