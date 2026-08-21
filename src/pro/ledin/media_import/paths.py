from __future__ import annotations

import os
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when an operation would escape an approved root."""


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def ensure_write_path(path: Path, roots: Iterable[Path]) -> Path:
    resolved = path.resolve()
    if not any(is_within(resolved, root) for root in roots):
        raise PathSafetyError(f"Refusing to write outside approved roots: {resolved}")
    return resolved


def atomic_write(path: Path, content: str | bytes, roots: Iterable[Path]) -> bool:
    destination = ensure_write_path(path, roots)
    payload = content.encode("utf-8") if isinstance(content, str) else content
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() == payload:
        return False
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return True


def safe_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    translated = "".join(
        "-" if char in "/\\:" or unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    collapsed = "-".join(translated.split()).strip(" .-")
    return collapsed or "source"


def output_path_for(relative_path: str, output_root: Path, source_hash: str) -> Path:
    source = Path(relative_path)
    parts = [safe_stem(part) for part in source.parts[:-1]]
    stem = safe_stem(source.stem)
    candidate = output_root.joinpath(*parts, f"{stem}.md")
    if candidate.exists():
        content = candidate.read_text(encoding="utf-8", errors="replace")
        if "importer: media-import" not in content and 'importer: "media-import"' not in content:
            candidate = candidate.with_name(f"{stem}-{source_hash[:8]}.md")
    return ensure_write_path(candidate, [output_root])
