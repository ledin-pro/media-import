from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when configuration is incomplete or unsafe."""


OCR_ENGINES = {"tesseract", "easyocr", "paddleocr", "paddleocr-vl-mlx", "vision"}
TRANSCRIPTION_PROVIDERS = {"auto", "existing", "docling-mlx", "docling-native", "off"}
TRANSCRIPTION_POLICIES = {"prefer-existing", "missing", "force"}
ASSET_MODES = {"reference", "copy"}
FRAME_MODES = {"text", "text-and-images", "images"}
LAYOUTS = {"mirror", "mapped"}
OFFICE_FALLBACKS = {"none", "auto", "markitdown", "pandoc"}


def _expanded_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _positive_int(value: Any, name: str, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class Config:
    source: str
    vault_root: Path
    output_dir: Path
    cache_dir: Path
    asset_mode: str = "reference"
    frame_mode: str = "text"
    layout: str = "mirror"
    path_map: dict[str, str] = field(default_factory=dict)
    office_fallback: str = "none"
    language: str = "auto"
    ocr_language: str = "auto"
    ocr_engine: str | None = None
    ocr_timeout_seconds: int = 600
    vision_api_url: str = ""
    vision_api_key: str = ""
    vision_model: str = ""
    paddle_vl_server_url: str = ""
    paddle_vl_model: str = ""
    transcription_provider: str = "auto"
    transcription_model: str = "whisper_turbo"
    transcription_language: str = "auto"
    transcription_timeout_seconds: int = 3600
    docling_device: str = "auto"
    docling_artifacts_path: Path | None = None
    transcription_policy: str = "prefer-existing"
    external_processing_approved: bool = False
    jobs: int = 1
    verbose: bool = False

    @property
    def output_root(self) -> Path:
        return (self.vault_root / self.output_dir).resolve()

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("vision_api_key", None)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
        data["output_root"] = str(self.output_root)
        return data


ENV_MAP = {
    "source": "MEDIA_IMPORT_SOURCE_DIR",
    "vault_root": "MEDIA_IMPORT_VAULT_ROOT",
    "output_dir": "MEDIA_IMPORT_TARGET_DIR",
    "cache_dir": "MEDIA_IMPORT_CACHE_DIR",
    "asset_mode": "MEDIA_IMPORT_ASSET_MODE",
    "frame_mode": "MEDIA_IMPORT_FRAME_MODE",
    "layout": "MEDIA_IMPORT_LAYOUT",
    "office_fallback": "MEDIA_IMPORT_OFFICE_FALLBACK",
    "language": "MEDIA_IMPORT_LANGUAGE",
    "ocr_language": "MEDIA_IMPORT_OCR_LANGUAGE",
    "ocr_engine": "MEDIA_IMPORT_OCR_ENGINE",
    "ocr_timeout_seconds": "MEDIA_IMPORT_OCR_TIMEOUT_SECONDS",
    "vision_api_url": "MEDIA_IMPORT_VISION_API_URL",
    "vision_api_key": "MEDIA_IMPORT_VISION_API_KEY",
    "vision_model": "MEDIA_IMPORT_VISION_MODEL",
    "paddle_vl_server_url": "MEDIA_IMPORT_PADDLE_VL_SERVER_URL",
    "paddle_vl_model": "MEDIA_IMPORT_PADDLE_VL_MODEL",
    "transcription_provider": "MEDIA_IMPORT_TRANSCRIPTION_PROVIDER",
    "transcription_model": "MEDIA_IMPORT_TRANSCRIPTION_MODEL",
    "transcription_language": "MEDIA_IMPORT_TRANSCRIPTION_LANGUAGE",
    "transcription_timeout_seconds": "MEDIA_IMPORT_TRANSCRIPTION_TIMEOUT_SECONDS",
    "docling_device": "MEDIA_IMPORT_DOCLING_DEVICE",
    "docling_artifacts_path": "MEDIA_IMPORT_DOCLING_ARTIFACTS_PATH",
    "transcription_policy": "MEDIA_IMPORT_TRANSCRIPTION_POLICY",
    "jobs": "MEDIA_IMPORT_JOBS",
}


def _file_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read configuration file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("Configuration file must contain a JSON object")
    return value


def load_config(
    *,
    overrides: Mapping[str, Any],
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    env = os.environ if environ is None else environ
    values = _file_config(config_path)
    for key, variable in ENV_MAP.items():
        value = env.get(variable, "").strip()
        if value:
            values[key] = value
    values.update({key: value for key, value in overrides.items() if value is not None})

    for name in ("source", "vault_root", "output_dir"):
        if not str(values.get(name, "")).strip():
            raise ConfigError(f"{name} is required")

    vault_root = _expanded_path(str(values["vault_root"]))
    output_value = Path(str(values["output_dir"]))
    if output_value.is_absolute():
        try:
            output_dir = output_value.resolve().relative_to(vault_root)
        except ValueError as exc:
            raise ConfigError("output_dir must be inside vault_root") from exc
    else:
        output_dir = output_value
    if any(part == ".." for part in output_dir.parts):
        raise ConfigError("output_dir must not escape vault_root")

    cache_dir = _expanded_path(str(values.get("cache_dir") or "~/.cache/media-import"))
    output_root = (vault_root / output_dir).resolve()
    if output_root == cache_dir or output_root.is_relative_to(cache_dir):
        raise ConfigError("output directory must not be inside the cache directory")

    asset_mode = str(values.get("asset_mode", "reference"))
    frame_mode = str(values.get("frame_mode", "text"))
    layout = str(values.get("layout", "mirror"))
    office_fallback = str(values.get("office_fallback", "none"))
    provider = str(values.get("transcription_provider", "auto"))
    policy = str(values.get("transcription_policy", "prefer-existing"))
    ocr_engine = str(values.get("ocr_engine") or "").strip() or None
    if asset_mode not in ASSET_MODES:
        raise ConfigError(f"Unsupported asset_mode: {asset_mode}")
    if frame_mode not in FRAME_MODES:
        raise ConfigError(f"Unsupported frame_mode: {frame_mode}")
    if layout not in LAYOUTS:
        raise ConfigError(f"Unsupported layout: {layout}")
    raw_path_map = values.get("path_map", {})
    if not isinstance(raw_path_map, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw_path_map.items()
    ):
        raise ConfigError("path_map must be a JSON object of source and destination prefixes")
    path_map = {key.strip("/"): value.strip("/") for key, value in raw_path_map.items()}
    if layout == "mapped" and not path_map:
        raise ConfigError("layout=mapped requires path_map in the configuration file")
    if office_fallback not in OFFICE_FALLBACKS:
        raise ConfigError(f"Unsupported office_fallback: {office_fallback}")
    if provider not in TRANSCRIPTION_PROVIDERS:
        raise ConfigError(f"Unsupported transcription provider: {provider}")
    if policy not in TRANSCRIPTION_POLICIES:
        raise ConfigError(f"Unsupported transcription policy: {policy}")
    if ocr_engine is not None and ocr_engine not in OCR_ENGINES:
        raise ConfigError(f"Unsupported OCR engine: {ocr_engine}")
    if provider == "existing" and policy == "force":
        raise ConfigError("provider=existing cannot be combined with policy=force")

    external_approved = bool(values.get("external_processing_approved", False))
    vision_key = str(values.get("vision_api_key", ""))
    vision_model = str(values.get("vision_model", ""))
    if ocr_engine == "vision":
        if not vision_key or not vision_model:
            raise ConfigError(
                "MEDIA_IMPORT_VISION_API_KEY and MEDIA_IMPORT_VISION_MODEL are required"
            )
        if not external_approved:
            raise ConfigError("External vision OCR requires explicit approval")

    paddle_url = str(values.get("paddle_vl_server_url", ""))
    paddle_model = str(values.get("paddle_vl_model", ""))
    if ocr_engine == "paddleocr-vl-mlx":
        if not paddle_url or not paddle_model:
            raise ConfigError(
                "MEDIA_IMPORT_PADDLE_VL_SERVER_URL and MEDIA_IMPORT_PADDLE_VL_MODEL are required"
            )
        if not (
            paddle_url.startswith("http://127.0.0.1") or paddle_url.startswith("http://localhost")
        ):
            raise ConfigError("PaddleOCR-VL service must use a loopback URL")

    jobs = _positive_int(values.get("jobs"), "jobs", 1)
    if jobs > 1:
        raise ConfigError("jobs greater than 1 are not supported for local model safety")
    artifacts = values.get("docling_artifacts_path")
    return Config(
        source=str(values["source"]),
        vault_root=vault_root,
        output_dir=output_dir,
        cache_dir=cache_dir,
        asset_mode=asset_mode,
        frame_mode=frame_mode,
        layout=layout,
        path_map=path_map,
        office_fallback=office_fallback,
        language=str(values.get("language", "auto")),
        ocr_language=str(values.get("ocr_language", "auto")),
        ocr_engine=ocr_engine,
        ocr_timeout_seconds=_positive_int(
            values.get("ocr_timeout_seconds"), "ocr_timeout_seconds", 600
        ),
        vision_api_url=str(values.get("vision_api_url", "")),
        vision_api_key=vision_key,
        vision_model=vision_model,
        paddle_vl_server_url=paddle_url,
        paddle_vl_model=paddle_model,
        transcription_provider=provider,
        transcription_model=str(values.get("transcription_model", "whisper_turbo")),
        transcription_language=str(
            values.get("transcription_language", values.get("language", "auto"))
        ),
        transcription_timeout_seconds=_positive_int(
            values.get("transcription_timeout_seconds"),
            "transcription_timeout_seconds",
            3600,
        ),
        docling_device=str(values.get("docling_device", "auto")),
        docling_artifacts_path=_expanded_path(str(artifacts)) if artifacts else None,
        transcription_policy=policy,
        external_processing_approved=external_approved,
        jobs=jobs,
        verbose=bool(values.get("verbose", False)),
    )
