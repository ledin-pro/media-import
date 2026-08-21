from pathlib import Path

import pytest

from pro.ledin.media_import.paths import (
    PathSafetyError,
    atomic_write,
    ensure_write_path,
    output_path_for,
)


def test_atomic_write_is_safe_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    path = root / "nested/file.txt"
    assert atomic_write(path, "hello", [root]) is True
    assert atomic_write(path, "hello", [root]) is False
    assert path.read_text() == "hello"
    with pytest.raises(PathSafetyError):
        ensure_write_path(tmp_path / "outside.txt", [root])


def test_manual_output_gets_stable_collision_suffix(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "lecture.md").write_text("manual", encoding="utf-8")
    assert output_path_for("lecture.mp4", root, "abcdef0123").name == "lecture-abcdef01.md"
