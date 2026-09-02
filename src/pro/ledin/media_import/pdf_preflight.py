from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class PdfPreflightError(RuntimeError):
    """Raised when a PDF cannot be prepared for local OCR."""


class PdfPasswordRequired(PdfPreflightError):
    """Raised when an unlocked PDF copy is required."""


def inspect_pdf_encryption(path: Path) -> dict[str, Any]:
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        return {"status": "unavailable", "tool": "qpdf", "error": "qpdf is not installed"}
    try:
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                return {
                    "status": "unreadable",
                    "tool": "qpdf",
                    "error": "file does not have a PDF header",
                }
    except OSError as exc:
        return {"status": "error", "tool": "qpdf", "error": str(exc)}
    try:
        completed = subprocess.run(
            [qpdf, "--requires-password", str(path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "tool": "qpdf", "error": str(exc)}
    if completed.returncode == 2:
        status = "not-encrypted"
    elif completed.returncode == 0:
        status = "password-required"
    elif completed.returncode == 3:
        status = "restrictions-only"
    else:
        status = "unreadable"
    result: dict[str, Any] = {"status": status, "tool": "qpdf"}
    if completed.stderr.strip():
        result["message"] = completed.stderr.strip()
    return result


@contextmanager
def decrypted_pdf(path: Path) -> Iterator[Path]:
    """Yield a temporary decrypted PDF without modifying the source."""
    if path.suffix.casefold() != ".pdf":
        yield path
        return
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="media-import-pdf-") as directory:
        output = Path(directory) / path.name
        command = [
            qpdf,
            "--decrypt",
            "--object-streams=disable",
            str(path),
            str(output),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0 or not output.exists():
            detail = (completed.stderr or completed.stdout or "qpdf decrypt failed").strip()
            raise PdfPreflightError(detail)
        yield output
