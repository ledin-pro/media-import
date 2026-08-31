from pathlib import Path
from types import SimpleNamespace

from pro.ledin.media_import.conflicts import (
    _probe_media,
    analyze_conflicts,
    ebook_variant_aliases,
    ebook_variant_groups,
    normalized_output_path,
)
from pro.ledin.media_import.dedupe import exact_duplicate_groups
from pro.ledin.media_import.inventory import SourceItem


def _item(
    source_path: str,
    extension: str,
    kind: str = "media",
    sha256: str | None = None,
) -> SourceItem:
    return SourceItem(
        source_path=source_path,
        absolute_path=None,
        source_uri=None,
        kind=kind,
        extension=extension,
        mime_type=None,
        size=None,
        mtime_ns=None,
        sha256=sha256 or source_path,
    )


def test_normalized_output_path_removes_source_extension() -> None:
    assert normalized_output_path("lesson/lecture.mp3") == "lesson/lecture.md"


def test_analyze_conflicts_groups_same_basename_media() -> None:
    items = [_item("lesson/lecture.mp3", ".mp3"), _item("lesson/lecture.mov", ".mov")]
    groups = analyze_conflicts(
        items,
        {item.source_path: normalized_output_path(item.source_path) for item in items},
    )

    assert len(groups) == 1
    assert groups[0]["reason"] == "same-basename"
    assert groups[0]["analysis_status"] == "transcript-needed"


def test_analyze_conflicts_detects_existing_owner_collision(tmp_path: Path) -> None:
    item = _item("lesson/lecture.mp3", ".mp3")
    output = tmp_path / "lesson/lecture.md"
    output.parent.mkdir()
    output.write_text("owned", encoding="utf-8")
    manifest = {
        "items": [
            {
                "source_path": "lesson/lecture.mov",
                "output_path": "lesson/lecture.md",
                "output_sha256": "not-the-file-hash",
            }
        ]
    }

    groups = analyze_conflicts(
        [item],
        {item.source_path: "lesson/lecture.md"},
        existing_manifest=manifest,
        output_root=tmp_path,
    )

    assert groups[0]["reason"] == "manual-edit"
    assert groups[0]["modified_owners"] == ["lesson/lecture.mov"]


def test_exact_duplicates_are_not_unresolved_conflicts() -> None:
    items = [
        _item("copy-a/lecture.mp3", ".mp3", sha256="same"),
        _item("copy-b/lecture.mp3", ".mp3", sha256="same"),
    ]
    groups = analyze_conflicts(items, {item.source_path: "lecture.md" for item in items})

    assert groups == []


def test_ebook_variants_group_by_directory_and_full_compound_suffix() -> None:
    items = [
        _item("fiction/book.fb2.zip", ".fb2.zip", kind="document"),
        _item("fiction/book.epub", ".epub", kind="document"),
        _item("reference/book.mobi", ".mobi", kind="document"),
    ]

    groups = ebook_variant_groups(items, ("fb2.zip", "epub", "mobi"))

    assert len(groups) == 1
    assert groups[0]["normalized_basename"] == "book"
    assert groups[0]["canonical_source_path"] == "fiction/book.fb2.zip"
    assert groups[0]["skipped_alternatives"] == ["fiction/book.epub"]
    assert groups[0]["content_compared"] is False
    assert "content was not compared" in groups[0]["warning"]
    assert ebook_variant_aliases(groups) == {"fiction/book.epub": "fiction/book.fb2.zip"}


def test_exact_hash_duplicate_prefers_ebook_format_order() -> None:
    items = [
        _item("book.azw", ".azw", kind="document", sha256="same"),
        _item("book.azw3", ".azw3", kind="document", sha256="same"),
    ]

    groups = exact_duplicate_groups(items, ("azw3", "azw"))

    assert groups[0]["canonical"] == "book.azw3"


def test_probe_media_selects_audio_stream(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "lecture.mov"
    source.write_bytes(b"media")
    item = SourceItem(
        source_path="lecture.mov",
        absolute_path=source,
        source_uri=None,
        kind="media",
        extension=".mov",
        mime_type="video/quicktime",
        size=5,
        mtime_ns=1,
        sha256="hash",
    )
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=(
                '{"format":{"duration":"12.5"},"streams":['
                '{"codec_type":"video","codec_name":"h264"},'
                '{"codec_type":"audio","codec_name":"aac",'
                '"sample_rate":"48000","channels":2}]}'
            ),
        ),
    )

    result = _probe_media(item)

    assert result["codec_name"] == "aac"
    assert result["sample_rate"] == "48000"
