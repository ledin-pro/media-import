from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import Config


class DoclingMediaError(RuntimeError):
    """Raised when Docling cannot convert a media source."""


def _prepare_huggingface_cache(config: Config) -> None:
    home = config.cache_dir / "huggingface"
    hub = home / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(home)
    os.environ["HF_HUB_CACHE"] = str(hub)
    try:
        import huggingface_hub.constants as constants
    except ImportError:
        return
    constants.HF_HOME = str(home)
    constants.HF_HUB_CACHE = str(hub)


def _asr_options(config: Config) -> Any:
    from docling.datamodel import asr_model_specs

    preset_name = config.transcription_model.upper().replace("-", "_")
    aliases = {
        "LARGE_V3_TURBO": "WHISPER_TURBO",
        "WHISPER_LARGE_V3_TURBO": "WHISPER_TURBO",
    }
    preset_name = aliases.get(preset_name, preset_name)
    if not preset_name.startswith("WHISPER_"):
        preset_name = f"WHISPER_{preset_name}"
    if config.transcription_provider == "docling-mlx":
        preset_name = f"{preset_name.removesuffix('_MLX').removesuffix('_NATIVE')}_MLX"
    elif config.transcription_provider == "docling-native":
        preset_name = f"{preset_name.removesuffix('_MLX').removesuffix('_NATIVE')}_NATIVE"
    try:
        options = deepcopy(getattr(asr_model_specs, preset_name))
    except AttributeError as exc:
        raise DoclingMediaError(f"Unknown Docling ASR preset: {preset_name}") from exc
    language = config.transcription_language
    if language and language != "auto" and hasattr(options, "language"):
        options.language = language
    return options


def _accelerator(config: Config) -> Any:
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions

    device = config.docling_device.casefold()
    if device == "auto":
        return AcceleratorOptions()
    try:
        return AcceleratorOptions(device=AcceleratorDevice(device))
    except ValueError:
        return AcceleratorOptions(device=device)


def convert_media(source: Path | str, config: Config, extension: str) -> Any:
    _prepare_huggingface_cache(config)
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import AsrPipelineOptions, VideoPipelineOptions
    from docling.document_converter import AudioFormatOption, DocumentConverter, VideoFormatOption
    from docling.pipeline.asr_pipeline import AsrPipeline
    from docling.utils.video_frame_sampling import VideoFrameSamplingMode

    asr_options = _asr_options(config)
    common = {
        "document_timeout": float(config.transcription_timeout_seconds),
        "accelerator_options": _accelerator(config),
        "artifacts_path": config.docling_artifacts_path,
    }
    video_extensions = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
    if extension.casefold() in video_extensions:
        pipeline_options = VideoPipelineOptions(
            frame_sampling_mode=VideoFrameSamplingMode.SCENE_CHANGE,
            cuts_per_minute=2.0,
            max_sampled_frames=40,
            generate_frame_images=True,
            enable_diarization=False,
            asr_options=asr_options,
            **common,
        )
        converter = DocumentConverter(
            format_options={InputFormat.VIDEO: VideoFormatOption(pipeline_options=pipeline_options)}
        )
    else:
        pipeline_options = AsrPipelineOptions(asr_options=asr_options, **common)
        converter = DocumentConverter(
            format_options={
                InputFormat.AUDIO: AudioFormatOption(
                    pipeline_cls=AsrPipeline,
                    pipeline_options=pipeline_options,
                )
            }
        )
    try:
        result = converter.convert(source)
    except Exception as exc:  # Docling exposes backend-specific exceptions.
        raise DoclingMediaError(f"Docling media conversion failed: {exc}") from exc
    if result.document is None:
        raise DoclingMediaError("Docling returned no document")
    return result
