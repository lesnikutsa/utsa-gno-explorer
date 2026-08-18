"""Conservative, non-executing GRC721 collection classification."""

from dataclasses import dataclass
import ast
import re

from api.token_identity import MAX_TOKEN_SOURCE_BYTES, MAX_TOKEN_SOURCE_FILES, _strip_comments

GRC721_PACKAGE_COMPONENTS = frozenset({"grc721", "grc721v2"})
CONSTRUCTORS = frozenset({"NewBasicNFT", "NewNFTWithMetadata"})
OWNERSHIP_READERS = frozenset({"OwnerOf"})
COLLECTION_SIGNALS = frozenset({
    "TokenURI", "TokenMetadata", "BalanceOf", "GetApproved", "Exists",
    "TransferFrom", "SafeTransferFrom", "Approve", "Mint", "Burn", "SetApprovalForAll",
})
SELF_CONTAINED_REQUIRED = frozenset({"Name", "Symbol", "OwnerOf", "TokenURI", "TransferFrom"})
SELF_CONTAINED_EVIDENCE = frozenset({
    "TokenCount", "TotalSupply", "BalanceOf", "Mint", "Burn", "Approve",
    "GetApproved", "SafeTransferFrom", "SetApprovalForAll",
})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")


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


def _implementation_component(path: str) -> str | None:
    normalized = path.rstrip("/")
    if not normalized or "/" not in normalized:
        return None
    component = normalized.rsplit("/", 1)[-1]
    return component if component in GRC721_PACKAGE_COMPONENTS else None


def _imports(source: str) -> set[str]:
    """Return usable aliases for recognized GRC721 imports in this file only."""
    clean = _strip_comments(source)
    aliases: set[str] = set()
    specs = list(re.finditer(r'(?m)^\s*import\s+(?:(?P<alias>\.|_|[A-Za-z_]\w*)\s+)?"(?P<path>[^"]+)"', clean))
    for block in re.finditer(r"(?s)\bimport\s*\((.*?)\)", clean):
        specs.extend(re.finditer(r'(?m)^\s*(?:(?P<alias>\.|_|[A-Za-z_]\w*)\s+)?"(?P<path>[^"]+)"', block.group(1)))
    for match in specs:
        component = _implementation_component(match.group("path"))
        alias = match.group("alias") or component
        if component and alias not in {".", "_"} and _IDENTIFIER_RE.fullmatch(alias):
            aliases.add(alias)
    return aliases


def inspect_grc721_candidate(files: list[dict], *, path_kind: str = "realm") -> GRC721Classification:
    """Expose the bounded recognized-import signal for read-only diagnostics."""
    if path_kind != "realm":
        return GRC721Classification("rejected", "not_realm")
    checked = _bounded_sources(files)
    if isinstance(checked, GRC721Classification):
        return checked
    bindings, ambiguous = _static_bindings(checked)
    self_contained = _self_contained_identity(checked, bindings, ambiguous)
    return (GRC721Classification("candidate", "implementation_import")
            if any(_imports(source) for source in checked) or self_contained
            else GRC721Classification("rejected", "implementation_import_missing"))


def _bounded_sources(files: list[dict]) -> list[str] | GRC721Classification:
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
        clean = _strip_comments(content)
        if content and not clean:
            return GRC721Classification("rejected", "malformed_source")
        sources.append(clean)
    if not sources:
        return GRC721Classification("rejected", "source_missing")
    return sources


def _constructor_calls(source: str, aliases: set[str]):
    if not aliases:
        return
    qualified = "|".join(re.escape(alias) for alias in sorted(aliases))
    constructors = "|".join(sorted(CONSTRUCTORS))
    for match in re.finditer(rf"\b(?:{qualified})\.(?P<constructor>{constructors})\s*\(", source):
        start, index, depth, quote = match.end(), match.end(), 1, None
        while index < len(source) and depth:
            char = source[index]
            if quote:
                if char == "\\":
                    index += 1
                elif char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        if depth == 0:
            yield match.group("constructor"), source[start:index - 1]
        else:
            yield match.group("constructor"), None


def _argument_parts(arguments: str) -> list[str] | None:
    parts, start, depth, quote, index = [], 0, 0, None, 0
    while index <= len(arguments):
        char = arguments[index] if index < len(arguments) else ","
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(arguments[start:index].strip())
            start = index + 1
        index += 1
    if parts and not parts[-1]:
        parts.pop()
    return parts if quote is None and depth == 0 else None


def _static_bindings(sources: list[str]) -> tuple[dict[str, str], set[str]]:
    values: dict[str, list[str | None]] = {}
    declaration = re.compile(r'(?m)^const\s+([A-Za-z_]\w*)\s*=\s*([^\n;]+)')
    grouped = re.compile(r'(?ms)^const\s*\((.*?)^\)')
    all_declarations: dict[str, int] = {}
    for source in sources:
        for match in re.finditer(r'(?m)^\s*(?:const|var)\s+([A-Za-z_]\w*)\s*=', source):
            all_declarations[match.group(1)] = all_declarations.get(match.group(1), 0) + 1
        for block in re.finditer(r'(?ms)^\s*const\s*\((.*?)^\s*\)', source):
            for match in re.finditer(r'(?m)^\s*([A-Za-z_]\w*)\s*=\s*([^\n;]+)', block.group(1)):
                all_declarations[match.group(1)] = all_declarations.get(match.group(1), 0) + 1
        for match in declaration.finditer(source):
            raw = match.group(2).strip()
            try:
                value = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                value = None
            values.setdefault(match.group(1), []).append(value if isinstance(value, str) else None)
        for block in grouped.finditer(source):
            for match in re.finditer(r'(?m)^\s*([A-Za-z_]\w*)\s*=\s*([^\n;]+)', block.group(1)):
                raw = match.group(2).strip()
                try:
                    value = ast.literal_eval(raw)
                except (SyntaxError, ValueError):
                    value = None
                values.setdefault(match.group(1), []).append(value if isinstance(value, str) else None)
    resolved = {name: definitions[0] for name, definitions in values.items()
                if len(definitions) == 1 and all_declarations.get(name) == 1
                and isinstance(definitions[0], str)}
    ambiguous = {name for name, count in all_declarations.items()
                 if count != 1 or name not in resolved}
    return resolved, ambiguous


def _resolve_identity_argument(raw: str, bindings: dict[str, str], ambiguous: set[str]) -> str | None:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        if not _IDENTIFIER_RE.fullmatch(raw) or raw in ambiguous:
            return None
        value = bindings.get(raw)
    return value if isinstance(value, str) else None


def _function_names(sources: list[str]) -> set[str]:
    pattern = re.compile(r"(?m)^\s*func\s+(?:\([^\n)]*\)\s*)?([A-Za-z_]\w*)\s*\(")
    return {match.group(1) for source in sources for match in pattern.finditer(source)}


def _package_function_names(sources: list[str]) -> set[str]:
    pattern = re.compile(r"(?m)^func\s+([A-Za-z_]\w*)\s*\(")
    return {match.group(1) for source in sources for match in pattern.finditer(source)}


def _static_function_return(sources: list[str], function_name: str,
                            bindings: dict[str, str], ambiguous: set[str]) -> str | None:
    returns: list[str | None] = []
    start_pattern = re.compile(rf"(?m)^func\s+{re.escape(function_name)}\s*\([^\n)]*\)[^{{\n]*\{{")
    for source in sources:
        for match in start_pattern.finditer(source):
            index, depth, quote = match.end(), 1, None
            while index < len(source) and depth:
                char = source[index]
                if quote:
                    if char == "\\": index += 1
                    elif char == quote: quote = None
                elif char in ('\"', "'"): quote = char
                elif char == "{": depth += 1
                elif char == "}": depth -= 1
                index += 1
            if depth:
                returns.append(None)
                continue
            body = source[match.end():index - 1].strip()
            result = re.fullmatch(r"return\s+(.+?)\s*;?", body, re.DOTALL)
            returns.append(_resolve_identity_argument(result.group(1).strip(), bindings, ambiguous)
                           if result else None)
    return returns[0] if len(returns) == 1 and returns[0] is not None else None


def _self_contained_identity(sources: list[str], bindings: dict[str, str],
                             ambiguous: set[str]) -> GRC721Identity | None:
    functions = _package_function_names(sources)
    if not SELF_CONTAINED_REQUIRED.issubset(functions):
        return None
    if len(functions & SELF_CONTAINED_EVIDENCE) < 2:
        return None
    name = _static_function_return(sources, "Name", bindings, ambiguous)
    symbol = _static_function_return(sources, "Symbol", bindings, ambiguous)
    if (name is None or symbol is None or not name or name != name.strip() or len(name) > 128 or
            not symbol or symbol != symbol.strip() or len(symbol) > 32):
        return None
    return GRC721Identity(name, symbol)


def classify_grc721(files: list[dict], *, path_kind: str = "realm",
                    qfunc_names: set[str] | frozenset[str] | None = None) -> GRC721Classification:
    """Verify one constructor-backed collection solely from bounded persisted source."""
    if path_kind != "realm":
        return GRC721Classification("rejected", "not_realm")
    checked = _bounded_sources(files)
    if isinstance(checked, GRC721Classification):
        return checked
    sources = checked
    bindings, ambiguous = _static_bindings(sources)
    self_contained = _self_contained_identity(sources, bindings, ambiguous)
    has_implementation_import = any(_imports(source) for source in sources)
    if not has_implementation_import:
        return (GRC721Classification("verified", "self_contained_collection", self_contained)
                if self_contained else GRC721Classification("rejected", "implementation_import_missing"))
    functions = _function_names(sources)
    if not (functions & OWNERSHIP_READERS) or not (functions & COLLECTION_SIGNALS):
        return GRC721Classification("rejected", "collection_behavior_missing")
    identities: list[tuple[str, str]] = []
    for source in sources:
        aliases = _imports(source)  # Imports are deliberately file-scoped.
        for _, arguments in _constructor_calls(source, aliases):
            parts = _argument_parts(arguments) if arguments is not None else None
            if parts is None or len(parts) < 2:
                return GRC721Classification("rejected", "dynamic_or_malformed_identity")
            name = _resolve_identity_argument(parts[-2], bindings, ambiguous)
            symbol = _resolve_identity_argument(parts[-1], bindings, ambiguous)
            if name is None or symbol is None:
                return GRC721Classification("rejected", "dynamic_or_malformed_identity")
            if (not name or name != name.strip() or len(name) > 128 or
                    not symbol or symbol != symbol.strip() or len(symbol) > 32):
                return GRC721Classification("rejected", "invalid_identity")
            identities.append((name, symbol))
    if len(identities) != 1:
        if not identities and self_contained:
            return GRC721Classification("verified", "self_contained_collection", self_contained)
        return GRC721Classification("rejected", "constructor_missing" if not identities else "ambiguous_identity")
    if self_contained and self_contained != GRC721Identity(*identities[0]):
        return GRC721Classification("rejected", "ambiguous_identity")
    return GRC721Classification("verified", "constructor_backed_collection", GRC721Identity(*identities[0]))


def extract_grc721_identity(files: list[dict]) -> GRC721Identity:
    classification = classify_grc721(files)
    return classification.identity if classification.status == "verified" else GRC721Identity()
