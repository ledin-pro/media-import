from pathlib import Path

from pro.ledin.media_import.config import Config
from pro.ledin.media_import.environment import run_preflight
from pro.ledin.media_import.inventory import SourceItem


def test_gigaam_preflight_reports_missing_package_without_importing(
    tmp_path: Path, monkeypatch
) -> None:
    looked_up = []

    def fake_find_spec(name):
        looked_up.append(name)
        return None if name == "docling_gigaam" else object()

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
        docling_device="cpu",
    )
    item = SourceItem(
        source_path="source.wav",
        absolute_path=tmp_path / "source.wav",
        source_uri=None,
        kind="media",
        extension=".wav",
        mime_type="audio/wav",
        size=1,
        mtime_ns=1,
        sha256="hash",
    )

    diagnostics = run_preflight(config, [item], for_import=False)

    assert "docling_gigaam" in looked_up
    assert any(item.code == "MISSING_DOCLING_GIGAAM" for item in diagnostics)


def test_mobi_preflight_requires_configured_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = Config(
        source="book.mobi",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    item = SourceItem(
        source_path="book.mobi",
        absolute_path=tmp_path / "book.mobi",
        source_uri=None,
        kind="document",
        extension=".mobi",
        mime_type="application/x-mobipocket-ebook",
        size=1,
        mtime_ns=1,
        sha256="hash",
    )

    diagnostics = run_preflight(config, [item], for_import=False)

    assert any(item.code == "MISSING_EBOOK_MOBI_BACKEND" for item in diagnostics)


def test_legacy_office_preflight_reports_missing_soffice_per_item(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = Config(
        source="legacy.doc",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    item = SourceItem(
        source_path="legacy.doc",
        absolute_path=tmp_path / "legacy.doc",
        source_uri=None,
        kind="document",
        extension=".doc",
        mime_type="application/msword",
        size=1,
        mtime_ns=1,
        sha256="hash",
    )

    diagnostics = run_preflight(config, [item], for_import=False)

    missing = next(item for item in diagnostics if item.code == "MISSING_SOFFICE")
    assert missing.level == "error"
    assert missing.source_path == "legacy.doc"
    assert missing.missing_component == "soffice"
