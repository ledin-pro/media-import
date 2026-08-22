from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .office_security import inspect_office_package
from .progress import ProgressReporter


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


OCR_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic"}


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


def _ocr_script(
    source: Path, config: Config, progress: ProgressReporter | None = None
) -> FallbackResult:
    executable = shutil.which("ocr")
    if executable is None:
        raise DoclingDocumentError("OCR CLI is not installed")

    engine = config.ocr_engine or "tesseract"
    command = [
        executable,
        str(source),
        "--engine",
        engine,
        "--format",
        "md,txt,json",
    ]
    if config.ocr_language != "auto":
        command.extend(["--lang", config.ocr_language])

    environment = os.environ.copy()
    if config.vision_api_url:
        environment["OCR_VISION_API_URL"] = config.vision_api_url
    if config.vision_api_key:
        environment["OCR_VISION_API_KEY"] = config.vision_api_key
    if config.vision_model:
        environment["OCR_VISION_MODEL"] = config.vision_model

    with tempfile.TemporaryDirectory(prefix="media-import-ocr-") as output_dir:
        command.extend(["--out", output_dir])
        started = time.monotonic()
        if progress:
            progress.emit(
                "ocr",
                "start",
                source=str(source),
                engine=engine,
            )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=config.ocr_timeout_seconds,
            env=environment,
        )
        markdown_path = Path(output_dir) / f"{source.stem}.md"
        if completed.returncode != 0 or not markdown_path.exists():
            detail = (completed.stderr or completed.stdout or "OCR returned no output").strip()
            if progress:
                progress.emit(
                    "ocr",
                    "failed",
                    source=str(source),
                    engine=engine,
                    elapsed=f"{time.monotonic() - started:.1f}s",
                )
            raise DoclingDocumentError(f"OCR CLI failed: {detail}")
        markdown = markdown_path.read_text(encoding="utf-8", errors="replace").strip()
        if not markdown:
            if progress:
                progress.emit(
                    "ocr",
                    "failed",
                    source=str(source),
                    engine=engine,
                    elapsed=f"{time.monotonic() - started:.1f}s",
                )
            raise DoclingDocumentError("OCR CLI returned empty output")
        if progress:
            progress.emit(
                "ocr",
                "complete",
                source=str(source),
                engine=engine,
                elapsed=f"{time.monotonic() - started:.1f}s",
            )
        return FallbackResult(FallbackDocument(markdown, "ocr"), "ocr")


def convert_document(
    source: Path | str,
    config: Config,
    progress: ProgressReporter | None = None,
) -> Any:
    from docling.document_converter import DocumentConverter

    if isinstance(source, Path) and source.suffix.casefold() in OCR_DOCUMENT_EXTENSIONS:
        return _ocr_script(source, config, progress)
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
