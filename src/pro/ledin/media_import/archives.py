from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .paths import ensure_write_path

MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024 * 1024
MAX_EXPANSION_RATIO = 200


class ArchiveError(ValueError):
    """Raised when an archive is invalid or unsafe."""


@dataclass(frozen=True)
class ArchiveSummary:
    members: int
    uncompressed_bytes: int
    compressed_bytes: int

    def public_dict(self) -> dict[str, int]:
        return {
            "members": self.members,
            "uncompressed_bytes": self.uncompressed_bytes,
            "compressed_bytes": self.compressed_bytes,
        }


def _safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ArchiveError(f"Unsafe archive path: {name}")
    if not path.parts:
        raise ArchiveError("Archive contains an empty path")
    return path


def _validate_limits(count: int, unpacked: int, packed: int) -> ArchiveSummary:
    if count > MAX_ARCHIVE_FILES:
        raise ArchiveError(f"Archive contains more than {MAX_ARCHIVE_FILES} members")
    if unpacked > MAX_ARCHIVE_BYTES:
        raise ArchiveError("Archive exceeds the uncompressed size limit")
    if packed > 0 and unpacked / packed > MAX_EXPANSION_RATIO:
        raise ArchiveError("Archive exceeds the expansion-ratio limit")
    return ArchiveSummary(count, unpacked, packed)


def inspect_archive(path: Path) -> ArchiveSummary:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            unpacked = 0
            packed = 0
            count = 0
            for member in archive.infolist():
                _safe_member(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ArchiveError(f"Archive symlink is not allowed: {member.filename}")
                if not member.is_dir():
                    count += 1
                    unpacked += member.file_size
                    packed += member.compress_size
            return _validate_limits(count, unpacked, packed)
    try:
        with tarfile.open(path) as archive:
            unpacked = 0
            count = 0
            for tar_member in archive.getmembers():
                _safe_member(tar_member.name)
                if tar_member.issym() or tar_member.islnk() or tar_member.isdev():
                    raise ArchiveError(f"Unsafe archive member: {tar_member.name}")
                if tar_member.isfile():
                    count += 1
                    unpacked += tar_member.size
            return _validate_limits(count, unpacked, path.stat().st_size)
    except tarfile.ReadError as exc:
        raise ArchiveError(f"Unsupported or invalid archive: {path}") from exc


def extract_archive(path: Path, destination: Path) -> ArchiveSummary:
    summary = inspect_archive(path)
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                relative = _safe_member(member.filename)
                target = ensure_write_path(destination.joinpath(*relative.parts), [destination])
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return summary
    with tarfile.open(path) as archive:
        for tar_member in archive.getmembers():
            relative = _safe_member(tar_member.name)
            target = ensure_write_path(destination.joinpath(*relative.parts), [destination])
            if tar_member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not tar_member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(tar_member)
            if extracted is None:
                raise ArchiveError(f"Cannot read archive member: {tar_member.name}")
            with extracted, target.open("wb") as output:
                shutil.copyfileobj(extracted, output)
    return summary


def download_archive(uri: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    request = urllib.request.Request(uri, headers={"User-Agent": "media-import/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            final_scheme = response.geturl().split(":", 1)[0].casefold()
            if final_scheme not in {"http", "https"}:
                raise ArchiveError("Archive redirect used an unsupported scheme")
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = output.name
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ArchiveError("Archive download exceeds the size limit")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        os.replace(temporary, destination)
        temporary = None
        return destination
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
