"""Conservative, non-executing GRC721 collection classification."""

from dataclasses import dataclass
import re

from api.token_identity import MAX_TOKEN_SOURCE_BYTES, MAX_TOKEN_SOURCE_FILES, _literal_arguments, _strip_comments

GRC721_IMPORT = "gno.land/p/demo/tokens/grc721"
REQUIRED_FUNCTIONS = frozenset({"BalanceOf", "OwnerOf", "TransferFrom"})


@dataclass(frozen=True)
class GRC721Identity:
    name: str | None = None
    symbol: str | None = None

    @property
    def verified(self) -> bool:
        return self.name is not None and self.symbol is not None


@dataclass(frozen=True)
class GRC721Classification:
    status: str
    reason: str
    identity: GRC721Identity = GRC721Identity()


def inspect_grc721_candidate(files: list[dict], *, path_kind: str = "realm") -> GRC721Classification:
    """Expose the initial official-import signal for diagnostics without verification."""
    if path_kind != "realm":
        return GRC721Classification("rejected", "not_realm")
    if len(files) > MAX_TOKEN_SOURCE_FILES:
        return GRC721Classification("rejected", "file_limit")
    total, imported = 0, False
    for file in files:
        if file.get("file_kind") != "gno_source" or not str(file.get("filename", "")).endswith(".gno"):
            continue
        content = file.get("content")
        if not isinstance(content, str):
            return GRC721Classification("rejected", "malformed_source")
        total += len(content.encode("utf-8"))
        if total > MAX_TOKEN_SOURCE_BYTES:
            return GRC721Classification("rejected", "source_limit")
        imported = imported or bool(_imports(content))
    return (GRC721Classification("candidate", "official_import") if imported else
            GRC721Classification("rejected", "official_import_missing"))


def _imports(source: str) -> set[str]:
    """Return aliases that explicitly import the one supported package."""
    clean = _strip_comments(source)
    aliases: set[str] = set()
    pattern = rf'(?m)^\s*import\s+(?:(?P<alias>[A-Za-z_]\w*)\s+)?{re.escape(chr(34) + GRC721_IMPORT + chr(34))}'
    for match in re.finditer(pattern, clean):
        aliases.add(match.group("alias") or "grc721")
    # Also support parenthesized import blocks without accepting dot imports.
    block_pattern = rf'(?m)^\s*(?:(?P<alias>[A-Za-z_]\w*)\s+)?{re.escape(chr(34) + GRC721_IMPORT + chr(34))}'
    for block in re.finditer(r"(?s)\bimport\s*\((.*?)\)", clean):
        for match in re.finditer(block_pattern, block.group(1)):
            aliases.add(match.group("alias") or "grc721")
    return aliases


def _constructor_calls(source: str, aliases: set[str]):
    clean = _strip_comments(source)
    if not aliases:
        return
    qualified = "|".join(re.escape(alias) for alias in sorted(aliases))
    for match in re.finditer(rf"\b(?:{qualified})\.NewBasicNFT\s*\(", clean):
        start, index, depth, quote = match.end(), match.end(), 1, None
        while index < len(clean) and depth:
            char = clean[index]
            if quote:
                if char == "\\": index += 1
                elif char == quote: quote = None
            elif char in ('"', "'"): quote = char
            elif char == "(": depth += 1
            elif char == ")": depth -= 1
            index += 1
        if depth == 0:
            yield clean[start:index - 1]


def classify_grc721(files: list[dict], *, path_kind: str = "realm",
                    qfunc_names: set[str] | frozenset[str] = REQUIRED_FUNCTIONS) -> GRC721Classification:
    """Classify persisted source; every uncertainty rejects rather than guesses."""
    if path_kind != "realm":
        return GRC721Classification("rejected", "not_realm")
    if len(files) > MAX_TOKEN_SOURCE_FILES:
        return GRC721Classification("rejected", "file_limit")
    total, sources = 0, []
    for file in files:
        if file.get("file_kind") != "gno_source" or not str(file.get("filename", "")).endswith(".gno"):
            continue
        content = file.get("content")
        if not isinstance(content, str):
            return GRC721Classification("rejected", "malformed_source")
        total += len(content.encode("utf-8"))
        if total > MAX_TOKEN_SOURCE_BYTES:
            return GRC721Classification("rejected", "source_limit")
        if content and not _strip_comments(content):
            return GRC721Classification("rejected", "malformed_source")
        sources.append((content, _imports(content)))
    if not any(aliases for _, aliases in sources):
        return GRC721Classification("rejected", "official_import_missing")
    if not REQUIRED_FUNCTIONS.issubset(qfunc_names):
        return GRC721Classification("rejected", "canonical_functions_missing")
    identities: list[tuple[str, str]] = []
    for source, aliases in sources:
        for call in _constructor_calls(source, aliases):
            arguments = _literal_arguments(call)
            if arguments is None or len(arguments) < 2:
                return GRC721Classification("rejected", "dynamic_or_malformed_identity")
            name, symbol = arguments[-2:]
            if not isinstance(name, str) or not isinstance(symbol, str):
                return GRC721Classification("rejected", "dynamic_or_malformed_identity")
            if (not name or name != name.strip() or len(name) > 128 or
                    not symbol or symbol != symbol.strip() or len(symbol) > 32):
                return GRC721Classification("rejected", "invalid_identity")
            identities.append((name, symbol))
    if len(identities) != 1:
        reason = "constructor_missing" if not identities else "ambiguous_identity"
        return GRC721Classification("rejected", reason)
    identity = GRC721Identity(*identities[0])
    return GRC721Classification("verified", "canonical_collection", identity)


def extract_grc721_identity(files: list[dict]) -> GRC721Identity:
    """Extract a bounded literal identity for tests and diagnostic consumers."""
    classification = classify_grc721(files)
    return classification.identity if classification.status == "verified" else GRC721Identity()
