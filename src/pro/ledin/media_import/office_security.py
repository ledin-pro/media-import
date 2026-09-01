from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_OFFICE_MEMBERS = 10_000
MAX_OFFICE_BYTES = 4 * 1024 * 1024 * 1024
MAX_OFFICE_EXPANSION_RATIO = 200
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt"}
REFERENCED_OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}


class OfficeSecurityError(ValueError):
    """Raised when an Office container contains unsafe active content."""


class OfficeDependencyError(RuntimeError):
    """Raised when a required Office conversion dependency is unavailable."""

    code = "missing_soffice"


@dataclass(frozen=True)
class OfficeInspection:
    members: int
    uncompressed_bytes: int


def find_soffice() -> str | None:
    """Return the installed LibreOffice command, if available."""
    return shutil.which("soffice") or shutil.which("libreoffice")


def require_soffice() -> str:
    executable = find_soffice()
    if executable is None:
        raise OfficeDependencyError(
            "Legacy Office import requires LibreOffice (soffice); install LibreOffice and retry"
        )
    return executable


def inspect_office_package(path: Path) -> OfficeInspection:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_OFFICE_MEMBERS:
                raise OfficeSecurityError("Office container has too many members")
            unpacked = sum(member.file_size for member in members)
            packed = sum(member.compress_size for member in members)
            if unpacked > MAX_OFFICE_BYTES:
                raise OfficeSecurityError("Office container exceeds the size limit")
            if packed > 0 and unpacked / packed > MAX_OFFICE_EXPANSION_RATIO:
                raise OfficeSecurityError("Office container exceeds the expansion-ratio limit")
            for member in members:
                normalized = PurePosixPath(member.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise OfficeSecurityError(f"Unsafe Office member path: {member.filename}")
                name = member.filename.casefold()
                if any(
                    marker in name
                    for marker in (
                        "vbaproject.bin",
                        "/activex/",
                        "/embeddings/",
                        "oleobject",
                    )
                ):
                    raise OfficeSecurityError(
                        f"Office active or embedded content is not allowed: {member.filename}"
                    )
                if name.endswith(".rels"):
                    payload = archive.read(member).lower()
                    if b'targetmode="external"' in payload or b"targetmode='external'" in payload:
                        raise OfficeSecurityError(
                            f"External Office relationship is not allowed: {member.filename}"
                        )
    except zipfile.BadZipFile as exc:
        raise OfficeSecurityError(f"Invalid Office container: {path}") from exc
    return OfficeInspection(len(members), unpacked)
