import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from ebook_helpers import make_fb2

from pro.ledin.media_import import cli
from pro.ledin.media_import.config import Config, ConfigError
from pro.ledin.media_import.inventory import SourceItem, inventory
from pro.ledin.media_import.manifest import load_manifest
from pro.ledin.media_import.pdf_preflight import PdfPasswordRequired
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

    def fake_process(item, items, resolved_config, output_root, progress=None, output_path=None):
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

    def fake_process(item, items, resolved_config, output_root, progress=None, output_path=None):
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


def test_cli_accepts_gigaam_provider() -> None:
    args = cli._parser().parse_args(
        [
            "inspect",
            "source.wav",
            "--vault-root",
            "/tmp/vault",
            "--output-dir",
            "corpus",
            "--transcription-provider",
            "gigaam",
        ]
    )
    assert args.transcription_provider == "gigaam"


def test_cli_accepts_ebook_options() -> None:
    args = cli._parser().parse_args(
        [
            "inspect",
            "book.fb2",
            "--vault-root",
            "/tmp/vault",
            "--output-dir",
            "books",
            "--ebook-image-policy",
            "ocr",
            "--ebook-ocr-prompt",
            "Read labels",
        ]
    )
    assert args.ebook_image_policy == "ocr"
    assert args.ebook_ocr_prompt == "Read labels"


def test_cli_accepts_ebook_format_preference() -> None:
    args = cli._parser().parse_args(
        [
            "inspect",
            "books",
            "--vault-root",
            "/tmp/vault",
            "--output-dir",
            "books",
            "--ebook-format-preference",
            "mobi,epub",
        ]
    )

    assert cli._overrides(args)["ebook_format_preference"] == "mobi,epub"


def test_cli_accepts_per_source_ebook_image_policies(tmp_path: Path) -> None:
    policies = tmp_path / "policies.json"
    policies.write_text('{"book.epub": "skip"}', encoding="utf-8")
    args = cli._parser().parse_args(
        [
            "inspect",
            "books",
            "--vault-root",
            "/tmp/vault",
            "--output-dir",
            "books",
            "--ebook-image-policies-file",
            str(policies),
        ]
    )
    assert cli._overrides(args)["ebook_image_policies"] == {"book.epub": "skip"}


def test_compound_fb2_zip_uses_book_output_stem(tmp_path: Path) -> None:
    config = Config(
        source="book.fb2.zip",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    item = SourceItem(
        source_path="book.fb2.zip",
        absolute_path=None,
        source_uri=None,
        kind="document",
        extension=".fb2.zip",
        mime_type="application/zip",
        size=None,
        mtime_ns=None,
        sha256="hash",
    )
    assert cli._output_source_path(item, config) == "book.fb2"


def test_compare_transcripts_subcommand_emits_json(tmp_path: Path, capsys) -> None:
    canonical = tmp_path / "canonical.md"
    variant = tmp_path / "variant.md"
    canonical.write_text("one two three " * 10, encoding="utf-8")
    variant.write_text("one two three " * 10, encoding="utf-8")

    result = cli.main(["compare-transcripts", str(canonical), str(variant), "--json"])

    assert result == 0
    assert json.loads(capsys.readouterr().out)["label"] == "full-equivalent"


def test_manifest_records_transcription_provider_and_model(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
    )

    def fake_process(item, items, resolved_config, output_root, progress=None, output_path=None):
        return (
            '---\nimporter: "media-import"\n---\n\n# Transcript\n',
            {
                "status": "complete",
                "errors": [],
                "transcription_provider": "gigaam",
                "transcription_model": "v3_e2e_rnnt",
            },
        )

    monkeypatch.setattr(cli, "_process_item", fake_process)
    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    assert manifest["config"]["transcription_provider"] == "gigaam"
    assert manifest["config"]["transcription_model"] == "v3_e2e_rnnt"
    assert manifest["items"][0]["transcription_provider"] == "gigaam"
    assert manifest["items"][0]["transcription_model"] == "v3_e2e_rnnt"
    assert manifest["items"][0]["requested_transcription_provider"] == "gigaam"
    assert manifest["items"][0]["resolved_transcription_provider"] == "gigaam"


def test_auto_route_change_invalidates_resume(tmp_path: Path) -> None:
    config = Config(
        source="source.wav",
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    russian = replace(
        config,
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
        transcription_language="ru",
        _route_auto_detected=True,
    )
    previous = {
        "resolved_transcription_provider": "auto",
        "resolved_transcription_model": "whisper_turbo",
        "resolved_transcription_language": "en",
    }

    assert cli._auto_route_matches(previous, russian) is False
    assert cli._auto_route_matches({}, russian) is False


def test_manifest_keeps_requested_auto_and_records_resolved_route(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    routed = replace(
        config,
        transcription_provider="gigaam",
        transcription_model="v3_e2e_rnnt",
        transcription_language="ru",
        _route_requested_provider="auto",
        _route_requested_model="whisper_turbo",
        _route_requested_language="auto",
        _route_detected_language="ru",
        _route_confidence=0.95,
        _route_sample_count=5,
        _route_status="complete",
        _route_method="test-detector",
        _route_reason="confident-russian",
        _route_auto_detected=True,
    )
    monkeypatch.setattr(cli, "resolve_media_route", lambda *args, **kwargs: routed)
    monkeypatch.setattr(cli, "run_preflight", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (
            '---\nimporter: "media-import"\n---\n\n# Transcript\n',
            {
                "status": "complete",
                "errors": [],
                "transcription_provider": "gigaam",
                "transcription_model": "v3_e2e_rnnt",
            },
        ),
    )

    cli._run_import(config, inventory(resolve_source(str(source))))

    manifest = load_manifest(config.output_root / "manifest.json")
    record = manifest["items"][0]
    assert manifest["config"]["transcription_provider"] == "auto"
    assert record["requested_transcription_provider"] == "auto"
    assert record["resolved_transcription_provider"] == "gigaam"
    assert record["detected_language"] == "ru"
    assert record["detection_confidence"] == 0.95


def test_same_basename_media_requires_decision_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "lesson.mp3").write_bytes(b"audio")
    (source / "lesson.mov").write_bytes(b"video")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ConfigError, match="Unresolved same-basename"):
        cli._run_import(config, inventory(resolve_source(str(source))))

    assert not config.output_root.exists()


@pytest.mark.parametrize("command", ["inspect", "import"])
def test_ebook_variants_are_reported_in_inspect_and_dry_run(
    tmp_path: Path, monkeypatch, capsys, command: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.fb2.zip").write_bytes(b"fb2")
    (source / "book.epub").write_bytes(b"epub")
    vault = tmp_path / "vault"
    monkeypatch.setattr(cli, "run_preflight", lambda config, items, for_import: [])

    arguments = [
        command,
        str(source),
        "--vault-root",
        str(vault),
        "--output-dir",
        "books",
    ]
    if command == "import":
        arguments.append("--dry-run")
    arguments.append("--json")

    result = cli.main(arguments)

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    group = report["ebook_variant_groups"][0]
    assert group["canonical_source_path"] == "book.epub"
    assert group["skipped_alternatives"] == ["book.fb2.zip"]
    assert group["content_compared"] is False
    assert "content was not compared" in group["warning"]
    if command == "import":
        assert report["unresolved_conflicts"] == []


def test_confirmed_ebook_variant_import_writes_only_canonical_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.fb2").write_bytes(b"fb2")
    (source / "book.epub").write_bytes(b"epub")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("books"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda item, items, resolved_config, output_root, progress=None, output_path=None: (
            '---\nimporter: "media-import"\n---\n\n# Book\n\nSample content.\n',
            {"status": "complete", "errors": []},
        ),
    )
    monkeypatch.setattr(cli, "run_preflight", lambda config, items, for_import: [])

    result = cli.main(
        [
            "import",
            str(source),
            "--vault-root",
            str(config.vault_root),
            "--output-dir",
            str(config.output_dir),
            "--confirmed",
        ]
    )

    assert result == 0
    manifest = load_manifest(config.output_root / "manifest.json")
    records = {item["source_path"]: item for item in manifest["items"]}
    assert records["book.epub"]["status"] == "complete"
    assert records["book.fb2"]["status"] == "duplicate"
    assert records["book.fb2"]["duplicate_reason"] == "ebook-variant"
    assert records["book.fb2"]["canonical_source_path"] == "book.epub"
    assert records["book.fb2"]["alias_of"] == "book.epub"
    assert records["book.fb2"]["content_compared"] is False
    assert "output_path" not in records["book.fb2"]
    assert (config.output_root / "book.md").is_file()
    content_outputs = sorted(
        path.relative_to(config.output_root).as_posix()
        for path in config.output_root.glob("*.md")
        if path.name not in {"catalog.md", "index.md"}
    )
    assert content_outputs == ["book.md"]


def test_decision_selects_canonical_and_marks_other_media_duplicate(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "lesson.mp3").write_bytes(b"audio")
    (source / "lesson.mov").write_bytes(b"video")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda item, items, resolved_config, output_root, progress=None, output_path=None: (
            '---\nimporter: "media-import"\n---\n\nTranscript\n',
            {"status": "complete", "errors": []},
        ),
    )

    items = inventory(resolve_source(str(source)))
    cli._run_import(config, items, conflict_decisions={"lesson.md": "lesson.mov"})
    manifest = load_manifest(config.output_root / "manifest.json")
    records = {item["source_path"]: item for item in manifest["items"]}

    assert records["lesson.mov"]["status"] == "complete"
    assert records["lesson.mp3"]["status"] == "duplicate"
    assert records["lesson.mp3"]["canonical_source_path"] == "lesson.mov"
    assert (config.output_root / "lesson.md").exists()


def test_mixed_type_collision_gets_separate_paths(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "lesson.mov").write_bytes(b"video")
    (source / "lesson.pdf").write_bytes(b"document")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda item, items, resolved_config, output_root, progress=None, output_path=None: (
            '---\nimporter: "media-import"\n---\n\nContent\n',
            {"status": "complete", "errors": []},
        ),
    )

    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    paths = {item["output_path"] for item in manifest["items"]}

    assert len(paths) == 2
    assert all(path.startswith("lesson-") for path in paths)


def test_password_protected_pdf_is_recorded_as_blocked(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "locked.pdf"
    source.write_bytes(b"pdf")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(PdfPasswordRequired("unlocked copy")),
    )

    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")

    assert manifest["items"][0]["status"] == "blocked"


def test_referenced_ebook_import_writes_and_resumes_assets(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "book.fb2"
    make_fb2(source)
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy="referenced",
    )

    first = cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    record = manifest["items"][0]
    asset = config.output_root / record["assets"][0]["path"]
    assert first["validation"]["status"] == "clean"
    assert asset.is_file()

    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should resume")),
    )
    cli._run_import(config, inventory(resolve_source(str(source))))
    resumed = load_manifest(config.output_root / "manifest.json")["items"][0]
    assert resumed["resumed"] is True


def test_modified_ebook_asset_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "book.fb2"
    make_fb2(source)
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy="referenced",
    )
    cli._run_import(config, inventory(resolve_source(str(source))))
    manifest = load_manifest(config.output_root / "manifest.json")
    asset = config.output_root / manifest["items"][0]["assets"][0]["path"]
    asset.write_bytes(b"manual")

    cli._run_import(config, inventory(resolve_source(str(source))))
    record = load_manifest(config.output_root / "manifest.json")["items"][0]

    assert record["status"] == "conflict"
    assert asset.read_bytes() == b"manual"


def test_changing_ebook_policy_removes_only_managed_assets(tmp_path: Path) -> None:
    source = tmp_path / "book.fb2"
    make_fb2(source)
    common = {
        "source": str(source),
        "vault_root": tmp_path / "vault",
        "output_dir": Path("corpus"),
        "cache_dir": tmp_path / "cache",
    }
    referenced = Config(**common, ebook_image_policy="referenced")
    cli._run_import(referenced, inventory(resolve_source(str(source))))
    manifest = load_manifest(referenced.output_root / "manifest.json")
    managed = referenced.output_root / manifest["items"][0]["assets"][0]["path"]
    user_file = managed.parent / "notes.txt"
    user_file.write_text("keep", encoding="utf-8")

    skipped = Config(**common, ebook_image_policy="skip")
    cli._run_import(skipped, inventory(resolve_source(str(source))))

    assert not managed.exists()
    assert user_file.read_text(encoding="utf-8") == "keep"


def test_ebook_ocr_error_redacts_prompt_and_api_key(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "book.fb2"
    source.write_bytes(b"book")
    prompt = "private recognition instructions"
    api_key = "top-secret-key"
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy="ocr",
        ebook_ocr_prompt=prompt,
        vision_api_key=api_key,
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"provider failed for {prompt} using {api_key}")
        ),
    )

    cli._run_import(config, inventory(resolve_source(str(source))))
    error = load_manifest(config.output_root / "manifest.json")["items"][0]["errors"][0]

    assert prompt not in error
    assert api_key not in error
    assert error.count("[redacted]") == 2


def test_ebook_ocr_error_redacts_normalized_prompt_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "book.fb2"
    source.write_bytes(b"book")
    prompt = "private file prompt"
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(f"  {prompt}\n", encoding="utf-8")
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy="ocr",
        ebook_ocr_prompt_file=prompt_file,
    )
    monkeypatch.setattr(
        cli,
        "_process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(prompt)),
    )

    cli._run_import(config, inventory(resolve_source(str(source))))
    error = load_manifest(config.output_root / "manifest.json")["items"][0]["errors"][0]

    assert prompt not in error
    assert error == "[redacted]"
