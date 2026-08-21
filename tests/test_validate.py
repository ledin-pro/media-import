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
