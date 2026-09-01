from __future__ import annotations

import importlib.util
import platform
import shutil
from dataclasses import asdict, dataclass

from .config import Config
from .ebook_documents import MOBI_EXTENSIONS, is_ebook_extension
from .inventory import SourceItem
from .office_security import LEGACY_OFFICE_EXTENSIONS, find_soffice


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    missing_component: str | None = None
    source_path: str | None = None

    def public_dict(self) -> dict[str, str | None]:
        return asdict(self)


def run_preflight(config: Config, items: list[SourceItem], *, for_import: bool) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    has_media = any(item.kind == "media" for item in items)
    has_visual_media = any(
        item.extension in {".avi", ".mkv", ".mov", ".mp4", ".webm"} for item in items
    )
    ebook_items = [item for item in items if is_ebook_extension(item.extension)]
    legacy_office_items = [
        item for item in items if item.extension in LEGACY_OFFICE_EXTENSIONS
    ]

    if importlib.util.find_spec("docling") is None:
        diagnostics.append(
            Diagnostic(
                "error",
                "MISSING_DOCLING",
                "Install docling and docling-slim[format-video].",
                "docling",
            )
        )
    if ebook_items:
        try:
            ebook_available = importlib.util.find_spec("pro.ledin.docling_ebook") is not None
        except ModuleNotFoundError:
            ebook_available = False
        if not ebook_available:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "MISSING_DOCLING_EBOOK",
                    "Install pro-ledin-docling-ebook>=0.2,<0.3 to import ebooks.",
                    "pro-ledin-docling-ebook",
                )
            )
        if any(item.extension in MOBI_EXTENSIONS for item in ebook_items):
            required = {
                "mobitool": ("mobitool",),
                "calibre": ("ebook-convert",),
                "auto": ("mobitool", "ebook-convert"),
            }[config.ebook_mobi_backend]
            if not any(shutil.which(executable) for executable in required):
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "MISSING_EBOOK_MOBI_BACKEND",
                        "MOBI/AZW import requires mobitool or Calibre ebook-convert.",
                        " or ".join(required),
                    )
                )
        if (
            any(config.ebook_image_policy_for(item.source_path) == "ocr" for item in ebook_items)
            and config.ebook_ocr_callback != "pro-ledin-ocr"
        ):
            module = config.ebook_ocr_callback.split(":", 1)[0]
            try:
                callback_available = bool(module) and importlib.util.find_spec(module) is not None
            except (ImportError, ModuleNotFoundError):
                callback_available = False
            if not callback_available:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "MISSING_EBOOK_OCR_CALLBACK",
                        f"Could not import ebook OCR callback module: {module}",
                        module,
                    )
                )
    if legacy_office_items and find_soffice() is None:
        diagnostics.extend(
            Diagnostic(
                "error",
                "MISSING_SOFFICE",
                "Legacy Office import requires LibreOffice (soffice).",
                "soffice",
                item.source_path,
            )
            for item in legacy_office_items
        )
    if has_media:
        for executable in ("ffmpeg", "ffprobe"):
            if shutil.which(executable) is None:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "MISSING_MEDIA_BINARY",
                        f"Docling media conversion requires {executable}.",
                        executable,
                    )
                )
    if has_visual_media and config.frame_mode in {"text", "text-and-images"}:
        if config.ocr_engine is None:
            diagnostics.append(
                Diagnostic(
                    "error" if for_import else "warning",
                    "MISSING_OCR_ENGINE",
                    "Set MEDIA_IMPORT_OCR_ENGINE to recognize sampled frame text.",
                    "MEDIA_IMPORT_OCR_ENGINE",
                )
            )
        elif importlib.util.find_spec("pro.ledin.ocr") is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "MISSING_OCR_PACKAGE",
                    "Install pro-ledin-ocr.",
                    "pro-ledin-ocr",
                )
            )
    if config.transcription_provider == "docling-mlx" and (
        platform.system() != "Darwin" or platform.machine() != "arm64"
    ):
        diagnostics.append(
            Diagnostic(
                "error",
                "MLX_REQUIRES_APPLE_SILICON",
                "docling-mlx requires Apple Silicon macOS.",
                "Apple Silicon",
            )
        )
    if has_media and config.transcription_provider == "gigaam":
        if importlib.util.find_spec("docling_gigaam") is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "MISSING_DOCLING_GIGAAM",
                    "Install docling-gigaam>=0.1,<0.2 to use the gigaam provider.",
                    "docling-gigaam",
                )
            )
        if importlib.util.find_spec("torch") is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "MISSING_GIGAAM_RUNTIME",
                    "The gigaam provider requires a PyTorch runtime supplied by docling-gigaam.",
                    "torch",
                )
            )
        device = config.docling_device.casefold()
        if device == "mlx":
            diagnostics.append(
                Diagnostic(
                    "error",
                    "GIGAAM_UNSUPPORTED_DEVICE",
                    "The gigaam provider does not support the MLX device; "
                    "use auto, cpu, cuda, or mps.",
                    "MEDIA_IMPORT_DOCLING_DEVICE",
                )
            )
        elif device == "mps" or (
            device == "auto" and platform.system() == "Darwin" and platform.machine() == "arm64"
        ):
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "GIGAAM_MPS_CAVEAT",
                    "GigaAM can use MPS, but its local Silero long-form path may run "
                    "unsupported operations on CPU.",
                    None,
                )
            )
    if config.docling_artifacts_path and not config.docling_artifacts_path.exists():
        diagnostics.append(
            Diagnostic(
                "error",
                "MISSING_DOCLING_ARTIFACTS",
                f"Docling artifacts path does not exist: {config.docling_artifacts_path}",
                str(config.docling_artifacts_path),
            )
        )
    return diagnostics


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(item.level == "error" for item in diagnostics)
