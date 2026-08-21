from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse


class SourceError(ValueError):
    """Raised when a source cannot be resolved safely."""


@dataclass(frozen=True)
class ResolvedSource:
    original: str
    kind: str
    local_path: Path | None
    source_uri: str | None
    display_name: str


def sanitize_uri(uri: str) -> str:
    parsed = urlparse(uri)
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, ""))


def resolve_source(value: str) -> ResolvedSource:
    parsed = urlparse(value)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).expanduser().resolve()
        if not path.exists():
            raise SourceError(f"Source does not exist: {path}")
        return ResolvedSource(
            value, "directory" if path.is_dir() else "file", path, None, path.name
        )
    if parsed.scheme in {"http", "https"}:
        if parsed.username or parsed.password:
            raise SourceError("Credential-bearing source URLs are not supported")
        name = Path(unquote(parsed.path)).name or parsed.hostname or "remote-source"
        return ResolvedSource(value, "remote", None, sanitize_uri(value), name)
    if parsed.scheme:
        raise SourceError(f"Unsupported source scheme: {parsed.scheme}")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise SourceError(f"Source does not exist: {path}")
    return ResolvedSource(value, "directory" if path.is_dir() else "file", path, None, path.name)
