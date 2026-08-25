from __future__ import annotations

import hashlib
import json
import mimetypes
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Config
from .paths import atomic_write, is_within

EBOOK_EXTENSIONS = {".epub", ".fb2", ".fb2.zip", ".fbz", ".mobi", ".azw", ".azw3"}
MOBI_EXTENSIONS = {".mobi", ".azw", ".azw3"}


def is_ebook_extension(extension: str) -> bool:
    return extension.casefold() in EBOOK_EXTENSIONS


def convert_ebook_document(
    source: Path | str,
    config: Config,
    output_path: Path,
    output_root: Path,
) -> tuple[str, Any, dict[str, Any]]:
    try:
        from pro.ledin.docling_ebook import (
            EbookConverter,
            OcrCallbackFactoryContext,
            document_for_public_export,
            load_json_config,
            load_ocr_callback,
            transform_pictures_with_ocr,
        )
    except ImportError as exc:
        raise RuntimeError("Ebook import requires pro-ledin-docling-ebook>=0.2,<0.3") from exc

    materialized_source = _materialize_source(source, config)
    converter = EbookConverter(
        source_image_mode="skip" if config.ebook_image_policy == "skip" else "import",
        mobi_backend=config.ebook_mobi_backend,
        footnote_mode=config.ebook_footnote_mode,
    )
    result = converter.convert(materialized_source)
    details: dict[str, Any] = {
        "conversion_route": "docling-ebook",
        "ebook_source_format": result.source_format,
        "ebook_image_policy": config.ebook_image_policy,
        "ebook_metadata": result.metadata,
        "ebook_warnings": list(result.warnings),
        "ebook_conversion": result.conversion,
        "assets": [],
        "image_occurrences": _image_occurrences(result),
        "unique_images": len(result.parsed_book.assets),
    }

    if config.ebook_image_policy == "skip":
        return result.export_to_markdown(), result.document, details

    if config.ebook_image_policy == "referenced":
        asset_dir_name = f"{output_path.stem}_artifacts"
        with tempfile.TemporaryDirectory(prefix="media-import-ebook-") as temporary:
            temporary_root = Path(temporary).resolve()
            artifacts_dir = temporary_root / asset_dir_name
            body = result.export_referenced_markdown(artifacts_dir)
            payloads: list[dict[str, Any]] = []
            for asset in sorted(artifacts_dir.rglob("*")):
                if not asset.is_file() or not is_within(asset, artifacts_dir):
                    continue
                relative_asset = asset.relative_to(artifacts_dir)
                if any(part in {"", ".", ".."} for part in relative_asset.parts):
                    raise ValueError(f"Unsafe ebook asset path: {relative_asset}")
                final_path = output_path.parent / asset_dir_name / relative_asset
                if not is_within(final_path, output_root):
                    raise ValueError(f"Ebook asset escapes output root: {relative_asset}")
                data = asset.read_bytes()
                payloads.append(
                    {
                        "path": final_path.relative_to(output_root).as_posix(),
                        "data": data,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size": len(data),
                        "media_type": mimetypes.guess_type(asset.name)[0],
                    }
                )
        details["asset_dir"] = (
            (output_path.parent / asset_dir_name).relative_to(output_root).as_posix()
        )
        details["_asset_payloads"] = payloads
        details["assets"] = [
            {key: value for key, value in item.items() if key != "data"} for item in payloads
        ]
        return body, result.document, details

    prompt = _ocr_prompt(config)
    callback_config, callback_config_hash = load_json_config(config.ebook_ocr_callback_config)
    profile = {
        "callback": config.ebook_ocr_callback,
        "callback_config_hash": callback_config_hash,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "timeout": config.ebook_ocr_timeout_seconds,
        "max_attempts": config.ebook_ocr_max_attempts,
    }
    profile_hash = hashlib.sha256(json.dumps(profile, sort_keys=True).encode("utf-8")).hexdigest()
    checkpoint = config.cache_dir / "docling-ebook-ocr" / result.sha256 / f"{profile_hash}.json"
    context = OcrCallbackFactoryContext(
        config=callback_config,
        config_hash=callback_config_hash,
        timeout=float(config.ebook_ocr_timeout_seconds),
        max_attempts=config.ebook_ocr_max_attempts,
        output_dir=output_path.parent,
        checkpoint_path=checkpoint,
    )
    callback = load_ocr_callback(
        config.ebook_ocr_callback,
        context,
        built_in_config={
            "api_url": config.vision_api_url,
            "api_key": config.vision_api_key,
            "model": config.vision_model,
        },
    )
    transformed = transform_pictures_with_ocr(
        result,
        callback,
        prompt,
        checkpoint,
        timeout=float(config.ebook_ocr_timeout_seconds),
        max_attempts=config.ebook_ocr_max_attempts,
        restart=config.ebook_restart_ocr,
    )
    document = document_for_public_export(transformed.document)
    details.update(
        {
            "ocr_checkpoint": str(transformed.checkpoint),
            "ocr_status": transformed.status,
            "image_occurrences": transformed.image_occurrences,
            "unique_images": transformed.unique_images,
            "ocr_completed_images": transformed.completed_images,
            "ocr_attempts": transformed.attempts,
        }
    )
    return document.export_to_markdown(), document, details


def _ocr_prompt(config: Config) -> str:
    if config.ebook_ocr_prompt_file is not None:
        try:
            prompt = config.ebook_ocr_prompt_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Could not read ebook OCR prompt: {exc}") from exc
    else:
        prompt = config.ebook_ocr_prompt
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Ebook OCR prompt must not be empty")
    return prompt


def _image_occurrences(result: Any) -> int:
    occurrences = sum(len(chapter.images) for chapter in result.parsed_book.chapters)
    if result.parsed_book.cover_image:
        occurrences += 1
    return occurrences


def _materialize_source(source: Path | str, config: Config) -> Path | str:
    if isinstance(source, Path) or not str(source).startswith(("http://", "https://")):
        return source
    url = str(source)
    name = Path(urlsplit(url).path).name or "book.epub"
    identity = hashlib.sha256(url.encode("utf-8")).hexdigest()
    destination = config.cache_dir / "downloads" / f"{identity}-{name}"
    if destination.is_file():
        return destination
    request = Request(url, headers={"User-Agent": "media-import/0.1"})
    limit = 100 * 1024 * 1024
    with urlopen(request, timeout=60) as response:  # noqa: S310 - explicit user source URL
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Remote ebook exceeds the 100 MiB download limit")
    atomic_write(destination, payload, [config.cache_dir])
    return destination
