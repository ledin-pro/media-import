from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import Config
from .paths import atomic_write


class VisualTextError(RuntimeError):
    """Raised when sampled-picture OCR fails."""


def existing_visual_text(item: Any) -> str:
    for annotation in getattr(item, "annotations", None) or []:
        for field in ("text", "description", "content"):
            value = getattr(annotation, field, None)
            if value and str(value).strip():
                return str(value).strip()
    return ""


def _ocr_options(config: Config) -> Any:
    import pro.ledin.ocr as ocr

    if config.ocr_engine is None:
        raise VisualTextError("OCR engine is not configured")
    return ocr.RecognizeOptions(
        engine=config.ocr_engine,
        lang=config.ocr_language,
        vision_api_url=config.vision_api_url,
        vision_api_key=config.vision_api_key,
        vision_model=config.vision_model,
        paddle_vl_server_url=config.paddle_vl_server_url,
        paddle_vl_model=config.paddle_vl_model,
        timeout=float(config.ocr_timeout_seconds),
        verbose=config.verbose,
    )


def recognize_picture(document: Any, item: Any, config: Config) -> dict[str, Any]:
    existing = existing_visual_text(item)
    if existing:
        return {"text": existing, "status": "reused", "engine": "docling"}
    try:
        image = item.get_image(document)
    except Exception as exc:
        raise VisualTextError(f"Cannot obtain Docling picture image: {exc}") from exc
    if image is None:
        return {"text": "", "status": "empty", "engine": config.ocr_engine}
    import pro.ledin.ocr as ocr

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temporary = Path(handle.name)
        image.save(temporary, format="PNG")
        pages = ocr.recognize(temporary, _ocr_options(config))
    except ocr.OcrError as exc:
        raise VisualTextError(str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    chunks = [str(page.get("markdown") or page.get("text") or "").strip() for page in pages]
    text = "\n\n".join(chunk for chunk in chunks if chunk)
    flags = [page.get("flag") for page in pages if page.get("flag")]
    return {
        "text": text,
        "status": "complete" if text else "empty",
        "engine": config.ocr_engine,
        "flags": flags,
    }


def save_picture(document: Any, item: Any, destination: Path, output_root: Path) -> None:
    try:
        image = item.get_image(document)
    except Exception as exc:
        raise VisualTextError(f"Cannot obtain Docling picture image: {exc}") from exc
    if image is None:
        raise VisualTextError("Docling picture item contains no image")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    atomic_write(destination, buffer.getvalue(), [output_root])
