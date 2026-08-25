from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path

from .progress import ProgressReporter
from .sources import ResolvedSource

MEDIA_EXTENSIONS = {
    ".aac",
    ".avi",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
DOCUMENT_EXTENSIONS = {
    ".azw",
    ".azw3",
    ".csv",
    ".doc",
    ".docx",
    ".epub",
    ".fb2",
    ".fb2.zip",
    ".fbz",
    ".html",
    ".jpeg",
    ".jpg",
    ".md",
    ".mobi",
    ".odf",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}
DOCLING_EXTENSIONS = {".dclx", ".doctags", ".vtt"}
ARCHIVE_EXTENSIONS = {".tar", ".tar.gz", ".tgz", ".zip"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceItem:
    source_path: str
    absolute_path: Path | None
    source_uri: str | None
    kind: str
    extension: str
    mime_type: str | None
    size: int | None
    mtime_ns: int | None
    sha256: str | None

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["absolute_path"] = str(self.absolute_path) if self.absolute_path else None
        return data


def source_extension(path: Path) -> str:
    name = path.name.casefold()
    if name.endswith(".fb2.zip"):
        return ".fb2.zip"
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    return path.suffix.casefold()


def _looks_like_docling_json(path: Path) -> bool:
    if path.suffix.casefold() != ".json":
        return False
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            prefix = handle.read(64 * 1024)
            if size > len(prefix):
                handle.seek(max(0, size - 64 * 1024))
                sample = prefix + handle.read(64 * 1024)
            else:
                sample = prefix
    except OSError:
        return False
    return b'"schema_name"' in sample and b'"DoclingDocument"' in sample


def classify(path: Path) -> str:
    extension = source_extension(path)
    if extension in MEDIA_EXTENSIONS:
        return "media"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    if extension in DOCLING_EXTENSIONS or _looks_like_docling_json(path):
        return "docling"
    if extension in ARCHIVE_EXTENSIONS:
        return "archive"
    return "unsupported"


def _local_item(path: Path, root: Path) -> SourceItem:
    stat = path.stat()
    relative = path.name if path == root else path.relative_to(root).as_posix()
    return SourceItem(
        source_path=relative,
        absolute_path=path,
        source_uri=None,
        kind=classify(path),
        extension=source_extension(path),
        mime_type=mimetypes.guess_type(path.name)[0],
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=sha256_file(path),
    )


def inventory(source: ResolvedSource, progress: ProgressReporter | None = None) -> list[SourceItem]:
    if source.kind == "remote":
        if progress:
            progress.emit("inventory", "complete", scope="remote", items=1)
        path = Path(source.display_name)
        return [
            SourceItem(
                source_path=source.display_name,
                absolute_path=None,
                source_uri=source.source_uri,
                kind=classify(path),
                extension=source_extension(path),
                mime_type=mimetypes.guess_type(path.name)[0],
                size=None,
                mtime_ns=None,
                sha256=None,
            )
        ]
    assert source.local_path is not None
    if source.local_path.is_file():
        if progress:
            progress.emit("inventory", "start", scope="source", files=1)
        item = _local_item(source.local_path, source.local_path)
        if progress:
            progress.emit("inventory", "complete", scope="source", items=1, hashed=1)
        return [item]
    paths = [
        path
        for path in source.local_path.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(source.local_path).parts)
        and not path.name.startswith("~$")
    ]
    ordered_paths = sorted(paths, key=lambda item: item.as_posix().casefold())
    if progress:
        progress.emit("inventory", "start", scope="source", files=len(ordered_paths))
    items: list[SourceItem] = []
    total = len(ordered_paths)
    for index, path in enumerate(ordered_paths, start=1):
        items.append(_local_item(path, source.local_path))
        if progress:
            progress.periodic(
                "inventory",
                "inventory",
                "progress",
                current=index,
                total=total,
                source=path.relative_to(source.local_path).as_posix(),
            )
    if progress:
        progress.emit("inventory", "complete", scope="source", items=total, hashed=total)
    return items
