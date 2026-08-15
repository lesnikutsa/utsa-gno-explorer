"""Conservative, non-executing identity extraction for persisted Gno source."""

from dataclasses import dataclass
import ast
import re

MAX_TOKEN_SOURCE_FILES = 32
MAX_TOKEN_SOURCE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class TokenIdentity:
    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None

    @property
    def verified(self) -> bool:
        return self.name is not None and self.symbol is not None and self.decimals is not None


def _strip_comments(source: str) -> str:
    """Remove comments while preserving quoted strings; this never evaluates source."""
    output, index, quote = [], 0, None
    while index < len(source):
        char = source[index]
        if quote:
            output.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                output.append(source[index])
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
            output.append(char)
        elif source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end - 1
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                return ""
            index = end + 1
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _calls(source: str):
    source = _strip_comments(source)
    for match in re.finditer(r"\b(?:[A-Za-z_]\w*\.)?NewToken\s*\(", source):
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
            yield source[start:index - 1]


def _literal_arguments(arguments: str) -> list[object] | None:
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
            raw = arguments[start:index].strip()
            try:
                parts.append(ast.literal_eval(raw))
            except (ValueError, SyntaxError):
                parts.append(None)
            start = index + 1
        index += 1
    return parts if quote is None and depth == 0 else None


def extract_token_identity(files: list[dict]) -> TokenIdentity:
    """Return identity only for one unique literal ``NewToken`` identity triple."""
    if len(files) > MAX_TOKEN_SOURCE_FILES:
        return TokenIdentity()
    total = 0
    identities: set[tuple[str, str, int]] = set()
    call_count = 0
    for file in files:
        if file.get("file_kind") != "gno_source" or not str(file.get("filename", "")).endswith(".gno"):
            continue
        content = file.get("content")
        if not isinstance(content, str):
            return TokenIdentity()
        total += len(content.encode("utf-8"))
        if total > MAX_TOKEN_SOURCE_BYTES:
            return TokenIdentity()
        for call in _calls(content):
            call_count += 1
            args = _literal_arguments(call)
            candidates = [] if args is None else [tuple(args[i:i + 3]) for i in range(max(0, len(args) - 2))
                if isinstance(args[i], str) and isinstance(args[i + 1], str)
                and type(args[i + 2]) is int and 0 <= args[i + 2] <= 30]
            if len(candidates) != 1:
                return TokenIdentity()
            name, symbol, decimals = candidates[0]
            if not name.strip() or name != name.strip() or len(name) > 128 or not symbol.strip() or symbol != symbol.strip() or len(symbol) > 32:
                return TokenIdentity()
            identities.add((name, symbol, decimals))
    if call_count != 1 or len(identities) != 1:
        return TokenIdentity()
    return TokenIdentity(*next(iter(identities)))
