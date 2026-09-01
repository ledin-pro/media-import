from __future__ import annotations

import hashlib
import importlib.util
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .office_security import (
    LEGACY_OFFICE_EXTENSIONS,
    REFERENCED_OFFICE_EXTENSIONS,
    inspect_office_package,
    require_soffice,
)
from .paths import is_within
from .pdf_preflight import PdfPasswordRequired, decrypted_pdf, inspect_pdf_encryption
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
        if source.suffix.casefold() == ".pdf":
            pdf_status = inspect_pdf_encryption(source)["status"]
            if pdf_status == "password-required":
                raise PdfPasswordRequired(
                    "PDF is password-protected; provide an unlocked copy"
                )
        with decrypted_pdf(source) as ocr_source:
            command[1] = str(ocr_source)
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
    extension = Path(str(source).split("?", 1)[0]).suffix.casefold()
    if extension in LEGACY_OFFICE_EXTENSIONS:
        require_soffice()
    if isinstance(source, Path) and extension in OCR_DOCUMENT_EXTENSIONS:
        return _ocr_script(source, config, progress)
    if isinstance(source, Path) and extension in REFERENCED_OFFICE_EXTENSIONS:
        inspect_office_package(source)
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    try:
        result = converter.convert(source)
    except Exception as exc:
        if isinstance(source, Path) and extension in REFERENCED_OFFICE_EXTENSIONS:
            return _fallback(source, config, exc)
        raise DoclingDocumentError(f"Docling document conversion failed: {exc}") from exc
    if result.document is None:
        error = DoclingDocumentError("Docling returned no document")
        if isinstance(source, Path) and extension in REFERENCED_OFFICE_EXTENSIONS:
            return _fallback(source, config, error)
        raise error
    if (
        not str(result.document.export_to_markdown()).strip()
        and isinstance(source, Path)
        and extension in REFERENCED_OFFICE_EXTENSIONS
    ):
        return _fallback(source, config, DoclingDocumentError("Docling returned empty output"))
    return result


def export_markdown(document: Any) -> str:
    return str(document.export_to_markdown()).strip()


def export_office_referenced_markdown(
    document: Any, output_path: Path, output_root: Path
) -> tuple[str, dict[str, Any]]:
    """Export a Docling Office document and stage its referenced images as assets."""
    from docling_core.types.doc import ImageRefMode

    asset_dir_name = f"{output_path.stem}_artifacts"
    payloads: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="media-import-office-") as temporary:
        temporary_root = Path(temporary).resolve()
        temporary_markdown = temporary_root / output_path.name
        temporary_assets = temporary_root / asset_dir_name
        document.save_as_markdown(
            temporary_markdown,
            artifacts_dir=Path(asset_dir_name),
            image_mode=ImageRefMode.REFERENCED,
        )
        body = temporary_markdown.read_text(encoding="utf-8")
        for asset in sorted(temporary_assets.rglob("*")):
            if not asset.is_file() or not is_within(asset, temporary_assets):
                continue
            relative_asset = asset.relative_to(temporary_assets)
            if any(part in {"", ".", ".."} for part in relative_asset.parts):
                raise ValueError(f"Unsafe Office asset path: {relative_asset}")
            final_path = output_path.parent / asset_dir_name / relative_asset
            if not is_within(final_path, output_root):
                raise ValueError(f"Office asset escapes output root: {relative_asset}")
            data = asset.read_bytes()
            media_type = mimetypes.guess_type(asset.name)[0]
            payloads.append(
                {
                    "path": final_path.relative_to(output_root).as_posix(),
                    "data": data,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                    "media_type": media_type,
                }
            )

    details = {
        "asset_dir": (output_path.parent / asset_dir_name).relative_to(output_root).as_posix(),
        "assets": [
            {key: value for key, value in payload.items() if key != "data"}
            for payload in payloads
        ],
        "_asset_payloads": payloads,
        "office_image_mode": ImageRefMode.REFERENCED.value,
    }
    return body.strip(), details
