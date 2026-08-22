import io
from pathlib import Path

from pro.ledin.media_import.dedupe import exact_duplicate_groups
from pro.ledin.media_import.inventory import inventory
from pro.ledin.media_import.progress import ProgressReporter
from pro.ledin.media_import.sources import resolve_source


def test_inventory_is_sorted_and_ignores_hidden_files(tmp_path: Path) -> None:
    (tmp_path / "b.mp3").write_bytes(b"same")
    (tmp_path / "a.mp4").write_bytes(b"same")
    (tmp_path / ".hidden.mp4").write_bytes(b"hidden")
    (tmp_path / "notes.pdf").write_bytes(b"pdf")
    items = inventory(resolve_source(str(tmp_path)))
    assert [item.source_path for item in items] == ["a.mp4", "b.mp3", "notes.pdf"]
    groups = exact_duplicate_groups(items)
    assert groups[0]["canonical"] == "a.mp4"
    assert groups[0]["aliases"] == ["b.mp3"]


def test_inventory_detects_canonical_docling_json(tmp_path: Path) -> None:
    export = tmp_path / "arbitrary-name.json"
    export.write_text(
        '{"schema_name":"DoclingDocument","name":"example","body":{"children":[]}}',
        encoding="utf-8",
    )
    items = inventory(resolve_source(str(export)))
    assert items[0].kind == "docling"


def test_inventory_reports_hashing_progress(tmp_path: Path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"audio")
    (tmp_path / "b.pdf").write_bytes(b"document")
    output = io.StringIO()
    progress = ProgressReporter(stream=output, verbose=True)

    inventory(resolve_source(str(tmp_path)), progress)

    text = output.getvalue()
    assert "phase=inventory status=start" in text
    assert "phase=inventory status=progress current=1 total=2" in text
    assert "phase=inventory status=complete" in text
