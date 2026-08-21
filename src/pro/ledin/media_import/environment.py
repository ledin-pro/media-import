from __future__ import annotations

import importlib.util
import platform
import shutil
from dataclasses import asdict, dataclass

from .config import Config
from .inventory import SourceItem


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    missing_component: str | None = None

    def public_dict(self) -> dict[str, str | None]:
        return asdict(self)


def run_preflight(config: Config, items: list[SourceItem], *, for_import: bool) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    has_media = any(item.kind == "media" for item in items)
    has_visual_media = any(
        item.extension in {".avi", ".mkv", ".mov", ".mp4", ".webm"} for item in items
    )

    if importlib.util.find_spec("docling") is None:
        diagnostics.append(
            Diagnostic(
                "error",
                "MISSING_DOCLING",
                "Install docling and docling-slim[format-video].",
                "docling",
            )
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
