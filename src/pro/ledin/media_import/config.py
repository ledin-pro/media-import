from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when configuration is incomplete or unsafe."""


OCR_ENGINES = {"tesseract", "easyocr", "paddleocr", "paddleocr-vl-mlx", "vision"}
TRANSCRIPTION_PROVIDERS = {
    "auto",
    "existing",
    "docling-mlx",
    "docling-native",
    "gigaam",
    "off",
}
TRANSCRIPTION_POLICIES = {"prefer-existing", "missing", "force"}
ASSET_MODES = {"reference", "copy"}
FRAME_MODES = {"none", "text", "text-and-images", "images"}
LAYOUTS = {"mirror", "mapped"}
OFFICE_FALLBACKS = {"none", "auto", "markitdown", "pandoc"}
EBOOK_IMAGE_POLICIES = {"skip", "referenced", "ocr"}
EBOOK_MOBI_BACKENDS = {"auto", "mobitool", "calibre"}
EBOOK_FOOTNOTE_MODES = {"native", "inline"}
EBOOK_FORMAT_PREFERENCE = ("epub", "fb2", "mobi", "azw3", "azw", "fbz", "fb2.zip")


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


def _boolean(value: Any, name: str, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _ebook_format_preference(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return EBOOK_FORMAT_PREFERENCE
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_values = list(value)
    else:
        raise ConfigError(
            "ebook_format_preference must be a comma-separated list or JSON array"
        )

    preference: list[str] = []
    for raw_value in raw_values:
        format_name = str(raw_value).strip().casefold().lstrip(".")
        if not format_name:
            raise ConfigError("ebook_format_preference cannot contain an empty format")
        if format_name not in EBOOK_FORMAT_PREFERENCE:
            raise ConfigError(f"Unsupported ebook format preference: {format_name}")
        if format_name in preference:
            raise ConfigError(
                f"ebook_format_preference contains duplicate format: {format_name}"
            )
        preference.append(format_name)
    return tuple(preference)


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
    ebook_image_policy: str = "referenced"
    ebook_image_policies: dict[str, str] = field(default_factory=dict)
    ebook_format_preference: tuple[str, ...] = EBOOK_FORMAT_PREFERENCE
    ebook_mobi_backend: str = "auto"
    ebook_footnote_mode: str = "native"
    ebook_ocr_prompt: str = ""
    ebook_ocr_prompt_file: Path | None = None
    ebook_ocr_callback: str = "pro-ledin-ocr"
    ebook_ocr_callback_config: Path | None = None
    ebook_ocr_timeout_seconds: int = 300
    ebook_ocr_max_attempts: int = 3
    ebook_restart_ocr: bool = False
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
    external_processing_approved: bool = True
    jobs: int = 1
    verbose: bool = False

    @property
    def output_root(self) -> Path:
        return (self.vault_root / self.output_dir).resolve()

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("vision_api_key", None)
        prompt = data.pop("ebook_ocr_prompt", "")
        if prompt:
            data["ebook_ocr_prompt_sha256"] = hashlib.sha256(
                str(prompt).encode("utf-8")
            ).hexdigest()
        if self.ebook_ocr_prompt_file and self.ebook_ocr_prompt_file.is_file():
            data["ebook_ocr_prompt_sha256"] = hashlib.sha256(
                self.ebook_ocr_prompt_file.read_bytes()
            ).hexdigest()
        if self.ebook_ocr_callback_config and self.ebook_ocr_callback_config.is_file():
            data["ebook_ocr_callback_config_sha256"] = hashlib.sha256(
                self.ebook_ocr_callback_config.read_bytes()
            ).hexdigest()
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
        data["ebook_format_preference"] = list(self.ebook_format_preference)
        data["output_root"] = str(self.output_root)
        return data

    def ebook_image_policy_for(self, source_path: str) -> str:
        return self.ebook_image_policies.get(source_path.strip("/"), self.ebook_image_policy)


ENV_MAP = {
    "source": "MEDIA_IMPORT_SOURCE_DIR",
    "vault_root": "MEDIA_IMPORT_VAULT_ROOT",
    "output_dir": "MEDIA_IMPORT_TARGET_DIR",
    "cache_dir": "MEDIA_IMPORT_CACHE_DIR",
    "asset_mode": "MEDIA_IMPORT_ASSET_MODE",
    "frame_mode": "MEDIA_IMPORT_FRAME_MODE",
    "layout": "MEDIA_IMPORT_LAYOUT",
    "office_fallback": "MEDIA_IMPORT_OFFICE_FALLBACK",
    "ebook_image_policy": "MEDIA_IMPORT_EBOOK_IMAGE_POLICY",
    "ebook_format_preference": "MEDIA_IMPORT_EBOOK_FORMAT_PREFERENCE",
    "ebook_mobi_backend": "MEDIA_IMPORT_EBOOK_MOBI_BACKEND",
    "ebook_footnote_mode": "MEDIA_IMPORT_EBOOK_FOOTNOTE_MODE",
    "ebook_ocr_prompt": "MEDIA_IMPORT_EBOOK_OCR_PROMPT",
    "ebook_ocr_prompt_file": "MEDIA_IMPORT_EBOOK_OCR_PROMPT_FILE",
    "ebook_ocr_callback": "MEDIA_IMPORT_EBOOK_OCR_CALLBACK",
    "ebook_ocr_callback_config": "MEDIA_IMPORT_EBOOK_OCR_CALLBACK_CONFIG",
    "ebook_ocr_timeout_seconds": "MEDIA_IMPORT_EBOOK_OCR_TIMEOUT_SECONDS",
    "ebook_ocr_max_attempts": "MEDIA_IMPORT_EBOOK_OCR_MAX_ATTEMPTS",
    "ebook_restart_ocr": "MEDIA_IMPORT_EBOOK_RESTART_OCR",
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
    ebook_image_policy = str(values.get("ebook_image_policy", "referenced"))
    raw_ebook_image_policies = values.get("ebook_image_policies", {})
    ebook_format_preference = _ebook_format_preference(values.get("ebook_format_preference"))
    ebook_mobi_backend = str(values.get("ebook_mobi_backend", "auto"))
    ebook_footnote_mode = str(values.get("ebook_footnote_mode", "native"))
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
    if ebook_image_policy not in EBOOK_IMAGE_POLICIES:
        raise ConfigError(f"Unsupported ebook_image_policy: {ebook_image_policy}")
    if not isinstance(raw_ebook_image_policies, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_ebook_image_policies.items()
    ):
        raise ConfigError("ebook_image_policies must be a JSON object of source paths to policies")
    ebook_image_policies = {
        key.strip("/"): value for key, value in raw_ebook_image_policies.items()
    }
    if any(not key for key in ebook_image_policies):
        raise ConfigError("ebook_image_policies cannot contain an empty source path")
    invalid_ebook_image_policies = set(ebook_image_policies.values()) - EBOOK_IMAGE_POLICIES
    if invalid_ebook_image_policies:
        raise ConfigError(
            "Unsupported ebook image policies: " + ", ".join(sorted(invalid_ebook_image_policies))
        )
    if ebook_mobi_backend not in EBOOK_MOBI_BACKENDS:
        raise ConfigError(f"Unsupported ebook_mobi_backend: {ebook_mobi_backend}")
    if ebook_footnote_mode not in EBOOK_FOOTNOTE_MODES:
        raise ConfigError(f"Unsupported ebook_footnote_mode: {ebook_footnote_mode}")
    if provider not in TRANSCRIPTION_PROVIDERS:
        raise ConfigError(f"Unsupported transcription provider: {provider}")
    if policy not in TRANSCRIPTION_POLICIES:
        raise ConfigError(f"Unsupported transcription policy: {policy}")
    if ocr_engine is not None and ocr_engine not in OCR_ENGINES:
        raise ConfigError(f"Unsupported OCR engine: {ocr_engine}")
    if provider == "existing" and policy == "force":
        raise ConfigError("provider=existing cannot be combined with policy=force")

    ebook_ocr_prompt = str(values.get("ebook_ocr_prompt", "")).strip()
    prompt_file_value = values.get("ebook_ocr_prompt_file")
    ebook_ocr_prompt_file = _expanded_path(str(prompt_file_value)) if prompt_file_value else None
    if ebook_ocr_prompt_file is not None and not ebook_ocr_prompt_file.is_file():
        raise ConfigError(f"Ebook OCR prompt file does not exist: {ebook_ocr_prompt_file}")
    callback_config_value = values.get("ebook_ocr_callback_config")
    ebook_ocr_callback_config = (
        _expanded_path(str(callback_config_value)) if callback_config_value else None
    )
    if ebook_ocr_callback_config is not None and not ebook_ocr_callback_config.is_file():
        raise ConfigError(f"Ebook OCR callback config does not exist: {ebook_ocr_callback_config}")
    ebook_ocr_callback = str(values.get("ebook_ocr_callback", "pro-ledin-ocr"))
    ebook_restart_ocr = _boolean(values.get("ebook_restart_ocr"), "ebook_restart_ocr")
    ebook_ocr_required = ebook_image_policy == "ocr" or "ocr" in ebook_image_policies.values()
    if not ebook_ocr_required and any(
        (
            ebook_ocr_prompt,
            ebook_ocr_prompt_file,
            callback_config_value,
            ebook_restart_ocr,
            ebook_ocr_callback != "pro-ledin-ocr",
        )
    ):
        raise ConfigError("Ebook OCR options require ebook_image_policy=ocr")
    external_approved = bool(values.get("external_processing_approved", True))
    vision_url = str(values.get("vision_api_url", ""))
    vision_key = str(values.get("vision_api_key", ""))
    vision_model = str(values.get("vision_model", ""))
    if ebook_ocr_required:
        if bool(ebook_ocr_prompt) == bool(ebook_ocr_prompt_file):
            raise ConfigError(
                "ebook_image_policy=ocr requires exactly one ebook OCR prompt or prompt file"
            )
        if ebook_ocr_callback == "pro-ledin-ocr":
            if not vision_url or not vision_key or not vision_model:
                raise ConfigError(
                    "Built-in ebook OCR requires MEDIA_IMPORT_VISION_API_URL, "
                    "MEDIA_IMPORT_VISION_API_KEY, and MEDIA_IMPORT_VISION_MODEL"
                )
            if not external_approved:
                raise ConfigError("External ebook OCR requires explicit approval")

    transcription_language = str(
        values.get("transcription_language", values.get("language", "auto"))
    )
    if provider == "gigaam" and transcription_language.casefold() not in {
        "auto",
        "ru",
        "rus",
        "russian",
    }:
        raise ConfigError(
            "GigaAM v3 supports Russian transcription only; use auto, ru, rus, or russian"
        )
    transcription_model = str(
        values.get(
            "transcription_model",
            "v3_e2e_rnnt" if provider == "gigaam" else "whisper_turbo",
        )
    )

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
        ebook_image_policy=ebook_image_policy,
        ebook_image_policies=ebook_image_policies,
        ebook_format_preference=ebook_format_preference,
        ebook_mobi_backend=ebook_mobi_backend,
        ebook_footnote_mode=ebook_footnote_mode,
        ebook_ocr_prompt=ebook_ocr_prompt,
        ebook_ocr_prompt_file=ebook_ocr_prompt_file,
        ebook_ocr_callback=ebook_ocr_callback,
        ebook_ocr_callback_config=ebook_ocr_callback_config,
        ebook_ocr_timeout_seconds=_positive_int(
            values.get("ebook_ocr_timeout_seconds"), "ebook_ocr_timeout_seconds", 300
        ),
        ebook_ocr_max_attempts=_positive_int(
            values.get("ebook_ocr_max_attempts"), "ebook_ocr_max_attempts", 3
        ),
        ebook_restart_ocr=ebook_restart_ocr,
        language=str(values.get("language", "auto")),
        ocr_language=str(values.get("ocr_language", "auto")),
        ocr_engine=ocr_engine,
        ocr_timeout_seconds=_positive_int(
            values.get("ocr_timeout_seconds"), "ocr_timeout_seconds", 600
        ),
        vision_api_url=vision_url,
        vision_api_key=vision_key,
        vision_model=vision_model,
        paddle_vl_server_url=paddle_url,
        paddle_vl_model=paddle_model,
        transcription_provider=provider,
        transcription_model=transcription_model,
        transcription_language=transcription_language,
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
