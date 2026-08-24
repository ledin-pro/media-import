import io
from pathlib import Path
from types import SimpleNamespace

from pro.ledin.media_import.config import Config
from pro.ledin.media_import.docling_documents import _ocr_script, _pandoc
from pro.ledin.media_import.progress import ProgressReporter


def test_pandoc_fallback_uses_argument_list(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "safe name.docx"
    source.write_bytes(b"office")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/pandoc")
    captured = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = arguments
        return SimpleNamespace(returncode=0, stdout="# Converted", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _pandoc(source)
    assert captured["arguments"] == [
        "/usr/local/bin/pandoc",
        str(source),
        "--to",
        "gfm",
    ]
    assert result.document.export_to_markdown() == "# Converted"


def test_config_accepts_explicit_office_fallback(tmp_path: Path) -> None:
    config = Config(
        source=str(tmp_path),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        office_fallback="pandoc",
    )
    assert config.office_fallback == "pandoc"


def test_ocr_script_routes_image_documents_without_exposing_key(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    config = Config(
        source=str(tmp_path),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ocr_engine="vision",
        vision_api_url="http://127.0.0.1:4000/v1",
        vision_api_key="secret",
        vision_model="model",
    )
    captured = {}

    monkeypatch.setattr(
        "shutil.which",
        lambda name: f"/usr/local/bin/{name}" if name in {"ocr", "qpdf"} else None,
    )

    def fake_run(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["environment"] = kwargs["env"]
        output_dir = Path(arguments[arguments.index("--out") + 1])
        (output_dir / "image.md").write_text("# OCR output", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    output = io.StringIO()
    result = _ocr_script(source, config, ProgressReporter(stream=output))

    assert result.route == "ocr"
    assert result.document.export_to_markdown() == "# OCR output"
    assert captured["arguments"][0].endswith("/ocr")
    assert "--decrypt" not in captured["arguments"]
    assert "secret" not in captured["arguments"]
    assert captured["environment"]["OCR_VISION_API_KEY"] == "secret"
    assert "phase=ocr status=start" in output.getvalue()
    assert "phase=ocr status=complete" in output.getvalue()
