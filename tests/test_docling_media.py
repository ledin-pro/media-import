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
