import json
from pathlib import Path
from types import SimpleNamespace

from pro.ledin.media_import import cli
from pro.ledin.media_import.config import Config
from pro.ledin.media_import.inventory import SourceItem, inventory
from pro.ledin.media_import.manifest import load_manifest
from pro.ledin.media_import.sources import resolve_source


def test_dry_run_does_not_create_vault_files(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "talk.mp3").write_bytes(b"audio")
    vault = tmp_path / "vault"
    monkeypatch.setattr(cli, "run_preflight", lambda config, items, for_import: [])
    result = cli.main(
        [
            "import",
            str(source),
            "--vault-root",
            str(vault),
            "--output-dir",
            "sources/talk",
            "--dry-run",
            "--json",
        ]
    )
    assert result == 0
    assert not vault.exists()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["dry_run"] is True
    assert "phase=inventory" in captured.err


def test_real_import_requires_confirmation(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"audio")
    monkeypatch.setattr(cli, "run_preflight", lambda config, items, for_import: [])
    result = cli.main(
        [
            "import",
            str(source),
            "--vault-root",
            str(tmp_path / "vault"),
            "--output-dir",
            "talk",
        ]
    )
    assert result == 3
    assert "requires --confirmed" in capsys.readouterr().err


def test_resume_reuses_unchanged_output_and_removes_owned_stale_file(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "note.txt"
    document.write_text("source", encoding="utf-8")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    calls = 0

    def fake_process(item, items, resolved_config, output_root, progress=None):
        nonlocal calls
        calls += 1
        return (
            '---\nimporter: "media-import"\n---\n\n# Note\n\nBody\n',
            {"status": "complete", "errors": []},
        )

    monkeypatch.setattr(cli, "_process_item", fake_process)
    items = inventory(resolve_source(str(source)))
    cli._run_import(config, items)
    cli._run_import(config, items)
    assert calls == 1
    manifest = load_manifest(config.output_root / "manifest.json")
    assert manifest["items"][0]["resumed"] is True

    document.unlink()
    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    assert manifest["items"][0]["status"] == "removed"
    assert not (config.output_root / "note.md").exists()


def test_vtt_events_preserve_cue_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "captions.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:01.250 --> 00:00:03.500\nHello world\n",
        encoding="utf-8",
    )
    events = cli._vtt_events(path)
    assert events[0].track is not None
    assert events[0].track.start_time == 1.25
    assert events[0].track.end_time == 3.5


def test_parse_only_rejects_unknown_scope() -> None:
    assert cli._parse_only("media,documents") == {"media", "documents"}


def test_cross_format_exact_text_is_deduplicated(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("first", encoding="utf-8")
    (source / "two.pdf").write_text("second", encoding="utf-8")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )

    def fake_process(item, items, resolved_config, output_root, progress=None):
        return (
            f'---\nimporter: "media-import"\n---\n\n# {item.source_path}\n\nSame\n',
            {"status": "complete", "errors": [], "content_sha256": "same-hash"},
        )

    monkeypatch.setattr(cli, "_process_item", fake_process)
    result = cli._run_import(config, inventory(resolve_source(str(source))))
    assert result["counts"] == {"complete": 1, "duplicate": 1}


def test_video_docling_cache_excludes_embedded_images(tmp_path: Path) -> None:
    captured = {}

    class Document:
        def model_dump(self, **kwargs):
            captured.update(kwargs)
            return {"pictures": [{"self_ref": "#/pictures/0"}]}

    item = SimpleNamespace(sha256="abc", source_path="video.mp4")
    config = SimpleNamespace(cache_dir=tmp_path)

    path = cli._cache_docling(Document(), item, config, exclude_images=True)

    assert path == str(tmp_path / "docling/abc.json")
    assert captured["exclude"] == {"pictures": {"__all__": {"image"}}}
    assert "data:image" not in Path(path).read_text(encoding="utf-8")


def test_mapped_layout_uses_longest_matching_prefix(tmp_path: Path) -> None:
    config = Config(
        source=str(tmp_path),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        layout="mapped",
        path_map={"course": "archive", "course/module": "lessons"},
    )
    item = SourceItem(
        source_path="course/module/lesson.mp4",
        absolute_path=None,
        source_uri=None,
        kind="media",
        extension=".mp4",
        mime_type="video/mp4",
        size=None,
        mtime_ns=None,
        sha256=None,
    )
    assert cli._output_source_path(item, config) == "lessons/lesson.mp4"


def test_write_indexes_creates_nested_directory_index(tmp_path: Path) -> None:
    output = tmp_path / "corpus"
    (output / "module").mkdir(parents=True)
    cli._write_indexes(
        output,
        [
            {
                "kind": "document",
                "source_path": "module/lesson.pdf",
                "output_path": "module/lesson.md",
                "status": "complete",
            }
        ],
    )
    nested = (output / "module/index.md").read_text(encoding="utf-8")
    assert "generated_by: media-import-directory-index" in nested
    assert "[[lesson]]" in nested
