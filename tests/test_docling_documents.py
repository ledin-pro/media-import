from pathlib import Path
from types import SimpleNamespace

from pro.ledin.media_import.config import Config
from pro.ledin.media_import.docling_documents import _pandoc


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
