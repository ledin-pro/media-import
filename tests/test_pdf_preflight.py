from pathlib import Path
from types import SimpleNamespace

import pytest

from pro.ledin.media_import.pdf_preflight import decrypted_pdf, inspect_pdf_encryption


def test_pdf_preflight_reports_missing_qpdf_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "locked.pdf"
    source.write_bytes(b"not-a-pdf")

    result = inspect_pdf_encryption(source)

    assert result["tool"] == "qpdf"
    assert result["status"] in {"unavailable", "unreadable", "error"}
    assert source.read_bytes() == b"not-a-pdf"


def test_decrypted_pdf_bypasses_non_pdf_when_qpdf_is_installed(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    called = False

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/qpdf")

    def fake_run(arguments, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr("subprocess.run", fake_run)
    with decrypted_pdf(source) as prepared:
        assert prepared == source

    assert called is False


def test_decrypted_pdf_uses_temporary_copy(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "restricted.pdf"
    source.write_bytes(b"encrypted")
    captured: dict[str, object] = {}

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/qpdf")

    def fake_run(arguments, **kwargs):
        captured["arguments"] = arguments
        output = Path(arguments[-1])
        output.write_bytes(b"decrypted")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    with decrypted_pdf(source) as decrypted:
        assert decrypted.read_bytes() == b"decrypted"

    assert "--decrypt" in captured["arguments"]
    assert source.read_bytes() == b"encrypted"


@pytest.mark.parametrize(
    ("returncode", "status"),
    [(2, "not-encrypted"), (3, "restrictions-only"), (0, "password-required")],
)
def test_pdf_preflight_maps_qpdf_status(
    tmp_path: Path, monkeypatch, returncode: int, status: str
) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"pdf")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/qpdf")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout="", stderr=""),
    )

    assert inspect_pdf_encryption(source)["status"] == status
