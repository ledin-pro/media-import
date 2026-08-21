from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .office_security import inspect_office_package


class DoclingDocumentError(RuntimeError):
    """Raised when a document conversion fails."""


@dataclass
class FallbackDocument:
    markdown: str
    route: str

    def export_to_markdown(self) -> str:
        return self.markdown

    def export_to_dict(self) -> dict[str, str]:
        return {
            "schema_name": "MediaImportFallback",
            "route": self.route,
            "markdown": self.markdown,
        }


@dataclass
class FallbackResult:
    document: FallbackDocument
    route: str
    status: str = "success"
    errors: tuple[str, ...] = ()


def _markitdown(source: Path) -> FallbackResult:
    from markitdown import MarkItDown

    markdown = str(MarkItDown().convert(source).markdown).strip()
    if not markdown:
        raise DoclingDocumentError("MarkItDown returned empty output")
    return FallbackResult(FallbackDocument(markdown, "markitdown"), "markitdown")


def _pandoc(source: Path) -> FallbackResult:
    executable = shutil.which("pandoc")
    if executable is None:
        raise DoclingDocumentError("Pandoc fallback is not installed")
    completed = subprocess.run(
        [executable, str(source), "--to", "gfm"],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        message = completed.stderr.strip() or "Pandoc returned empty output"
        raise DoclingDocumentError(f"Pandoc fallback failed: {message}")
    return FallbackResult(FallbackDocument(completed.stdout.strip(), "pandoc"), "pandoc")


def _fallback(source: Path, config: Config, cause: Exception) -> FallbackResult:
    choices = (
        ("markitdown", "pandoc") if config.office_fallback == "auto" else (config.office_fallback,)
    )
    errors = [str(cause)]
    for choice in choices:
        if choice == "none":
            break
        try:
            if choice == "markitdown":
                if importlib.util.find_spec("markitdown") is None:
                    raise DoclingDocumentError("MarkItDown fallback is not installed")
                return _markitdown(source)
            if choice == "pandoc":
                return _pandoc(source)
        except DoclingDocumentError as exc:
            errors.append(str(exc))
    raise DoclingDocumentError("; ".join(errors)) from cause


def convert_document(source: Path | str, config: Config) -> Any:
    from docling.document_converter import DocumentConverter

    if isinstance(source, Path) and source.suffix.casefold() in {".docx", ".pptx", ".xlsx"}:
        inspect_office_package(source)
    converter = DocumentConverter()
    try:
        result = converter.convert(source)
    except Exception as exc:
        if isinstance(source, Path) and source.suffix.casefold() in {".docx", ".pptx", ".xlsx"}:
            return _fallback(source, config, exc)
        raise DoclingDocumentError(f"Docling document conversion failed: {exc}") from exc
    if result.document is None:
        error = DoclingDocumentError("Docling returned no document")
        if isinstance(source, Path) and source.suffix.casefold() in {".docx", ".pptx", ".xlsx"}:
            return _fallback(source, config, error)
        raise error
    if (
        not str(result.document.export_to_markdown()).strip()
        and isinstance(source, Path)
        and source.suffix.casefold() in {".docx", ".pptx", ".xlsx"}
    ):
        return _fallback(source, config, DoclingDocumentError("Docling returned empty output"))
    return result


def export_markdown(document: Any) -> str:
    return str(document.export_to_markdown()).strip()
