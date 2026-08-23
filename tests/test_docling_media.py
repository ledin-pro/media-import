from pathlib import Path

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
