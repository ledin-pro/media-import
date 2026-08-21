import zipfile
from pathlib import Path

import pytest

from pro.ledin.media_import.archives import ArchiveError, extract_archive, inspect_archive


def test_safe_zip_is_inspected_and_extracted(tmp_path: Path) -> None:
    archive_path = tmp_path / "media.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("folder/talk.txt", "hello")
    summary = inspect_archive(archive_path)
    assert summary.members == 1
    output = tmp_path / "output"
    extract_archive(archive_path, output)
    assert (output / "folder/talk.txt").read_text() == "hello"


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "bad")
    with pytest.raises(ArchiveError, match="Unsafe archive path"):
        inspect_archive(archive_path)
