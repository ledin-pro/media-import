from pathlib import Path

from pro.ledin.media_import.inventory import sha256_file
from pro.ledin.media_import.manifest import new_manifest, save_manifest
from pro.ledin.media_import.validate import validate_corpus


def test_validation_detects_modified_owned_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    artifact = output / "talk.md"
    artifact.write_text('---\nimporter: "media-import"\n---\n\n# Talk\n', encoding="utf-8")
    (output / "index.md").write_text("# Index", encoding="utf-8")
    (output / "catalog.md").write_text("# Catalog", encoding="utf-8")
    manifest = new_manifest({}, {})
    manifest["items"] = [
        {
            "source_path": "talk.mp3",
            "status": "complete",
            "output_path": "talk.md",
            "output_sha256": sha256_file(artifact),
        }
    ]
    save_manifest(output / "manifest.json", manifest, output)
    artifact.write_text(artifact.read_text() + "manual edit\n", encoding="utf-8")
    result = validate_corpus(output)
    assert result["status"] == "failed"
    assert "Owned output was modified" in result["errors"][0]


def test_validation_detects_modified_ebook_asset(tmp_path: Path) -> None:
    output = tmp_path / "output"
    assets = output / "book_artifacts"
    assets.mkdir(parents=True)
    artifact = output / "book.md"
    asset = assets / "cover.png"
    asset.write_bytes(b"image")
    artifact.write_text(
        '---\nimporter: "media-import"\n---\n\n![cover](book_artifacts/cover.png)\n',
        encoding="utf-8",
    )
    (output / "index.md").write_text("# Index", encoding="utf-8")
    (output / "catalog.md").write_text("# Catalog", encoding="utf-8")
    manifest = new_manifest({}, {})
    manifest["items"] = [
        {
            "source_path": "book.fb2",
            "status": "complete",
            "output_path": "book.md",
            "output_sha256": sha256_file(artifact),
            "assets": [
                {
                    "path": "book_artifacts/cover.png",
                    "sha256": sha256_file(asset),
                }
            ],
        }
    ]
    save_manifest(output / "manifest.json", manifest, output)
    asset.write_bytes(b"modified")

    result = validate_corpus(output)

    assert result["status"] == "failed"
    assert any("Owned ebook asset was modified" in error for error in result["errors"])


def test_validation_rejects_ebook_image_path_escape(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    artifact = output / "book.md"
    artifact.write_text(
        '---\nimporter: "media-import"\n---\n\n![cover](../cover.png)\n',
        encoding="utf-8",
    )
    (output / "index.md").write_text("# Index", encoding="utf-8")
    (output / "catalog.md").write_text("# Catalog", encoding="utf-8")
    manifest = new_manifest({}, {})
    manifest["items"] = [
        {
            "source_path": "book.fb2",
            "status": "complete",
            "output_path": "book.md",
            "output_sha256": sha256_file(artifact),
        }
    ]
    save_manifest(output / "manifest.json", manifest, output)

    result = validate_corpus(output)

    assert any("Unsafe Markdown image" in error for error in result["errors"])
