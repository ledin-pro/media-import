import hashlib
import json
from pathlib import Path

import pytest
from docling_core.types.doc import ImageRefMode

from pro.ledin.media_import import cli
from pro.ledin.media_import.config import Config
from pro.ledin.media_import.environment import Diagnostic
from pro.ledin.media_import.inventory import inventory
from pro.ledin.media_import.manifest import load_manifest
from pro.ledin.media_import.sources import resolve_source
from pro.ledin.media_import.validate import validate_corpus


class FakeOfficeDocument:
    def export_to_dict(self):
        return {"schema_name": "FakeOffice"}

    def export_to_markdown(self):
        return "Office text"

    def save_as_markdown(self, filename, *, artifacts_dir, image_mode):
        assert image_mode is ImageRefMode.REFERENCED
        artifacts = Path(filename).parent / artifacts_dir
        artifacts.mkdir(parents=True)
        (artifacts / "image.png").write_bytes(b"office image")
        Path(filename).write_text("![image](report_artifacts/image.png)\n", encoding="utf-8")


class FakeOfficeResult:
    document = FakeOfficeDocument()
    status = "success"
    errors = ()
    route = "docling"


@pytest.mark.parametrize("suffix", [".docx", ".xlsx", ".pptx"])
def test_office_referenced_assets_resume_conflict_and_validate(
    tmp_path: Path, monkeypatch, suffix: str
) -> None:
    source = tmp_path / f"report{suffix}"
    source.write_bytes(b"office source")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())
    items = inventory(resolve_source(str(source)))

    first = cli._run_import(config, items)
    manifest = load_manifest(config.output_root / "manifest.json")
    record = manifest["items"][0]
    asset_record = record["assets"][0]
    asset = config.output_root / asset_record["path"]

    assert first["validation"]["status"] == "clean"
    assert record["office_image_mode"] == "referenced"
    assert asset_record["sha256"] == hashlib.sha256(b"office image").hexdigest()
    assert asset_record["size"] == len(b"office image")
    assert asset_record["media_type"] == "image/png"
    assert asset.is_file()
    assert "report_artifacts/image.png" in (config.output_root / record["output_path"]).read_text(
        encoding="utf-8"
    )

    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should resume")),
    )
    cli._run_import(config, items)
    assert load_manifest(config.output_root / "manifest.json")["items"][0]["resumed"] is True

    asset.write_bytes(b"manual")
    validation = validate_corpus(config.output_root)
    assert validation["status"] == "failed"
    assert any("Owned managed asset was modified" in error for error in validation["errors"])

    result = cli._run_import(config, items)
    record = load_manifest(config.output_root / "manifest.json")["items"][0]
    assert result["validation"]["status"] == "failed"
    assert record["status"] == "conflict"
    assert asset.read_bytes() == b"manual"


def test_legacy_office_without_soffice_is_blocked_in_import(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy office")
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = cli.main(
        [
            "import",
            str(source),
            "--vault-root",
            str(tmp_path / "vault"),
            "--output-dir",
            "corpus",
            "--confirmed",
            "--json",
        ]
    )

    assert result == 3
    manifest = load_manifest(tmp_path / "vault/corpus/manifest.json")
    record = manifest["items"][0]
    assert record["status"] == "blocked"
    assert record["diagnostics"][0]["code"] == "MISSING_SOFFICE"
    assert record["diagnostics"][0]["source_path"] == "legacy.doc"


def test_duplicate_office_with_assets_is_manifest_json_safe(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.docx").write_bytes(b"one")
    (source / "two.docx").write_bytes(b"two")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())

    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    records = {record["source_path"]: record for record in manifest["items"]}

    duplicate = records["two.docx"]
    assert duplicate["status"] == "duplicate"
    assert duplicate["canonical_output_path"] == "one.md"
    assert all(key not in duplicate for key in ("assets", "asset_dir", "office_image_mode"))
    json.dumps(manifest)


def test_resume_legacy_happens_before_missing_soffice_block(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy office")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())
    items = inventory(resolve_source(str(source)))
    cli._run_import(config, items)

    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should resume")),
    )
    cli._run_import(
        config,
        items,
        preflight_diagnostics=[
            Diagnostic(
                "error",
                "MISSING_SOFFICE",
                "Legacy Office import requires LibreOffice (soffice).",
                "soffice",
                "legacy.doc",
            )
        ],
    )

    assert load_manifest(config.output_root / "manifest.json")["items"][0]["resumed"] is True


def test_cli_resume_legacy_ignores_missing_soffice_exit_error(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy office")
    cache_dir = tmp_path / "cache"
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=cache_dir,
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())
    cli._run_import(config, inventory(resolve_source(str(source))))
    monkeypatch.setenv("MEDIA_IMPORT_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should resume")),
    )
    monkeypatch.setattr(
        cli,
        "run_preflight",
        lambda *args, **kwargs: [
            Diagnostic(
                "error",
                "MISSING_SOFFICE",
                "Legacy Office import requires LibreOffice (soffice).",
                "soffice",
                "legacy.doc",
            )
        ],
    )

    result = cli.main(
        [
            "import",
            str(source),
            "--vault-root",
            str(tmp_path / "vault"),
            "--output-dir",
            "corpus",
            "--confirmed",
            "--json",
        ]
    )

    assert result == 0
    assert load_manifest(config.output_root / "manifest.json")["items"][0]["resumed"] is True


def test_office_asset_writes_roll_back_when_markdown_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"office source")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())
    original_atomic_write = cli.atomic_write

    def fail_markdown(path, content, roots):
        if path == config.output_root / "report.md":
            raise OSError("markdown write failed")
        return original_atomic_write(path, content, roots)

    monkeypatch.setattr(cli, "atomic_write", fail_markdown)

    cli._run_import(config, inventory(resolve_source(str(source))))

    assert not (config.output_root / "report_artifacts/image.png").exists()


def test_stale_missing_office_markdown_removes_assets(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "report.docx"
    document.write_bytes(b"office source")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(cli, "convert_document", lambda *args, **kwargs: FakeOfficeResult())
    cli._run_import(config, inventory(resolve_source(str(source))))
    (config.output_root / "report.md").unlink()
    document.unlink()

    result = cli._run_import(config, inventory(resolve_source(str(source))))

    assert result["counts"] == {"removed": 1}
    assert not (config.output_root / "report_artifacts/image.png").exists()
