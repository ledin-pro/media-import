import sys
from pathlib import Path
from types import ModuleType

import pytest

import pro.ledin.media_import.docling_media as docling_media
from pro.ledin.media_import.config import Config


def test_prepare_huggingface_cache_uses_import_cache(tmp_path: Path, monkeypatch) -> None:
    import huggingface_hub.constants

    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    docling_media._prepare_huggingface_cache(config)
    assert (config.cache_dir / "huggingface/hub").is_dir()
    assert str(config.cache_dir / "huggingface/hub") == huggingface_hub.constants.HF_HUB_CACHE


def test_media_converter_is_reused_for_matching_options(tmp_path: Path, monkeypatch) -> None:
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    calls = 0
    converter = object()

    def fake_build(resolved_config, extension):
        nonlocal calls
        calls += 1
        return converter

    monkeypatch.setattr(docling_media, "_build_media_converter", fake_build)
    monkeypatch.setattr(docling_media, "_MEDIA_CONVERTERS", {})

    assert docling_media._get_media_converter(config, ".wav") is converter
    assert docling_media._get_media_converter(config, ".mp3") is converter
    assert calls == 1


def test_video_converter_skips_frames_when_frame_mode_is_none(tmp_path: Path) -> None:
    from docling.datamodel.base_models import InputFormat

    config = Config(
        source="source.mp4",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        frame_mode="none",
    )

    converter = docling_media._build_media_converter(config, ".mp4")
    options = converter.format_to_options[InputFormat.VIDEO].pipeline_options

    assert options.generate_frame_images is False


def test_gigaam_video_uses_public_factory_with_common_options(tmp_path: Path, monkeypatch) -> None:
    import docling.document_converter
    from docling.datamodel.base_models import InputFormat
    from docling.utils.video_frame_sampling import VideoFrameSamplingMode

    captured = {}
    module = ModuleType("docling_gigaam")

    class GigaAmOptions:
        def __init__(self, **kwargs):
            captured["model_options"] = kwargs

    def audio_format_option(options, **kwargs):
        captured["audio"] = (options, kwargs)
        return "audio-option"

    def video_format_option(options, **kwargs):
        captured["video"] = (options, kwargs)
        return "video-option"

    class DocumentConverter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.GigaAmOptions = GigaAmOptions
    module.audio_format_option = audio_format_option
    module.video_format_option = video_format_option
    monkeypatch.setitem(sys.modules, "docling_gigaam", module)
    monkeypatch.setattr(docling.document_converter, "DocumentConverter", DocumentConverter)
    artifacts = tmp_path / "artifacts"
    config = Config(
        source="source.mp4",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
        transcription_language="rus",
        transcription_timeout_seconds=123,
        docling_device="cpu",
        docling_artifacts_path=artifacts,
        frame_mode="text",
    )

    converter = docling_media._build_media_converter(config, ".mp4")

    assert captured["model_options"] == {
        "model_name": "v3_e2e_rnnt",
        "language": "ru",
        "device": "cpu",
    }
    _, kwargs = captured["video"]
    assert kwargs["document_timeout"] == 123.0
    assert kwargs["artifacts_path"] == artifacts
    assert kwargs["frame_sampling_mode"] == VideoFrameSamplingMode.SCENE_CHANGE
    assert kwargs["cuts_per_minute"] == 2.0
    assert kwargs["max_sampled_frames"] == 40
    assert kwargs["generate_frame_images"] is True
    assert kwargs["enable_diarization"] is False
    assert converter.kwargs["format_options"] == {InputFormat.VIDEO: "video-option"}
    assert "audio" not in captured


def test_gigaam_audio_uses_public_factory(tmp_path: Path, monkeypatch) -> None:
    import docling.document_converter
    from docling.datamodel.base_models import InputFormat

    captured = {}
    module = ModuleType("docling_gigaam")

    class GigaAmOptions:
        def __init__(self, **kwargs):
            captured["model_options"] = kwargs

    def audio_format_option(options, **kwargs):
        captured["audio"] = (options, kwargs)
        return "audio-option"

    module.GigaAmOptions = GigaAmOptions
    module.audio_format_option = audio_format_option
    module.video_format_option = lambda options, **kwargs: "video-option"

    class DocumentConverter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(sys.modules, "docling_gigaam", module)
    monkeypatch.setattr(docling.document_converter, "DocumentConverter", DocumentConverter)
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
    )

    converter = docling_media._build_media_converter(config, ".wav")

    assert converter.kwargs["format_options"] == {InputFormat.AUDIO: "audio-option"}
    assert captured["audio"][1]["document_timeout"] == 3600.0


def test_converter_cache_separates_gigaam_from_whisper(tmp_path: Path) -> None:
    common = {
        "source": "source.wav",
        "vault_root": tmp_path / "vault",
        "output_dir": Path("corpus"),
        "cache_dir": tmp_path / "cache",
    }
    whisper = Config(**common)
    gigaam = Config(
        **common,
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
    )

    assert docling_media._converter_key(whisper, ".wav") != docling_media._converter_key(
        gigaam, ".wav"
    )


def test_gigaam_missing_package_has_clear_error(tmp_path: Path, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def reject_gigaam(name, *args, **kwargs):
        if name == "docling_gigaam":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_gigaam)
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
    )

    with pytest.raises(docling_media.DoclingMediaError, match="requires docling-gigaam"):
        docling_media._build_media_converter(config, ".wav")
