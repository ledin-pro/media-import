from pathlib import Path

import pytest

from pro.ledin.media_import.config import ConfigError, load_config


def test_config_precedence_and_secret_redaction(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text('{"frame_mode":"images","jobs":2}', encoding="utf-8")
    config = load_config(
        overrides={
            "source": str(tmp_path),
            "vault_root": tmp_path / "vault",
            "output_dir": "sources/demo",
            "frame_mode": "text",
            "external_processing_approved": True,
        },
        config_path=config_file,
        environ={
            "MEDIA_IMPORT_JOBS": "1",
            "MEDIA_IMPORT_OCR_ENGINE": "vision",
            "MEDIA_IMPORT_VISION_API_KEY": "secret",
            "MEDIA_IMPORT_VISION_MODEL": "model",
        },
    )
    assert config.frame_mode == "text"
    assert config.jobs == 1
    assert config.output_root == (tmp_path / "vault/sources/demo").resolve()
    assert "vision_api_key" not in config.public_dict()
    assert "secret" not in str(config.public_dict())


def test_config_supports_disabling_frame_processing(tmp_path: Path) -> None:
    config = load_config(
        overrides={
            "source": str(tmp_path),
            "vault_root": tmp_path / "vault",
            "output_dir": "sources/demo",
            "frame_mode": "none",
        },
        environ={
            "MEDIA_IMPORT_OCR_ENGINE": "vision",
            "MEDIA_IMPORT_VISION_API_KEY": "secret",
            "MEDIA_IMPORT_VISION_MODEL": "model",
        },
    )
    assert config.frame_mode == "none"
    assert config.external_processing_approved is True


def test_config_rejects_output_escape(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="inside vault_root"):
        load_config(
            overrides={
                "source": str(tmp_path),
                "vault_root": tmp_path / "vault",
                "output_dir": tmp_path / "elsewhere",
            },
            environ={},
        )


def test_config_rejects_remote_paddle_service(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="loopback"):
        load_config(
            overrides={
                "source": str(tmp_path),
                "vault_root": tmp_path / "vault",
                "output_dir": "out",
            },
            environ={
                "MEDIA_IMPORT_OCR_ENGINE": "paddleocr-vl-mlx",
                "MEDIA_IMPORT_PADDLE_VL_SERVER_URL": "https://remote.example",
                "MEDIA_IMPORT_PADDLE_VL_MODEL": "model",
            },
        )


def test_mapped_layout_requires_path_map(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="requires path_map"):
        load_config(
            overrides={
                "source": str(tmp_path),
                "vault_root": tmp_path / "vault",
                "output_dir": "out",
                "layout": "mapped",
            },
            environ={},
        )


def test_parallel_jobs_are_rejected_until_model_execution_is_safe(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="greater than 1"):
        load_config(
            overrides={
                "source": str(tmp_path),
                "vault_root": tmp_path / "vault",
                "output_dir": "out",
                "jobs": 2,
            },
            environ={},
        )


def test_gigaam_uses_provider_default_model(tmp_path: Path) -> None:
    config = load_config(
        overrides={
            "source": str(tmp_path),
            "vault_root": tmp_path / "vault",
            "output_dir": "out",
            "transcription_provider": "gigaam",
        },
        environ={},
    )
    assert config.transcription_model == "v3_e2e_rnnt"


def test_gigaam_preserves_explicit_model(tmp_path: Path) -> None:
    config = load_config(
        overrides={
            "source": str(tmp_path),
            "vault_root": tmp_path / "vault",
            "output_dir": "out",
            "transcription_provider": "gigaam",
            "transcription_model": "custom-model",
        },
        environ={},
    )
    assert config.transcription_model == "custom-model"


@pytest.mark.parametrize("language", ["auto", "ru", "rus", "russian", "RUSSIAN"])
def test_gigaam_accepts_russian_languages(tmp_path: Path, language: str) -> None:
    config = load_config(
        overrides={
            "source": str(tmp_path),
            "vault_root": tmp_path / "vault",
            "output_dir": "out",
            "transcription_provider": "gigaam",
            "transcription_language": language,
        },
        environ={},
    )
    assert config.transcription_language == language


def test_gigaam_rejects_non_russian_language(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="supports Russian transcription only"):
        load_config(
            overrides={
                "source": str(tmp_path),
                "vault_root": tmp_path / "vault",
                "output_dir": "out",
                "transcription_provider": "gigaam",
                "transcription_language": "en",
            },
            environ={},
        )
