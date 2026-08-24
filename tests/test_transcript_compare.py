from pathlib import Path

from pro.ledin.media_import.transcript_compare import compare_transcripts


def test_compare_transcripts_rejects_insufficient_evidence(tmp_path: Path) -> None:
    left = tmp_path / "left.md"
    right = tmp_path / "right.md"
    left.write_text("short text", encoding="utf-8")
    right.write_text("short text", encoding="utf-8")

    assert compare_transcripts(left, right)["label"] == "insufficient-evidence"


def test_partial_variant_label_is_symmetric(tmp_path: Path) -> None:
    left = tmp_path / "left.md"
    right = tmp_path / "right.md"
    shared = " ".join(f"word{index}" for index in range(100))
    extra = " ".join(f"extra{index}" for index in range(20))
    left.write_text(f"{shared} {extra}", encoding="utf-8")
    right.write_text(shared, encoding="utf-8")

    forward = compare_transcripts(left, right)
    reverse = compare_transcripts(right, left)

    assert forward["label"] == "partial-variant"
    assert reverse["label"] == "partial-variant"
