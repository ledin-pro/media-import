import zipfile
from pathlib import Path

import pytest

from pro.ledin.media_import.office_security import OfficeSecurityError, inspect_office_package


def test_office_package_rejects_macros(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document />")
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(OfficeSecurityError, match="active or embedded"):
        inspect_office_package(path)


def test_office_package_rejects_external_relationships(tmp_path: Path) -> None:
    path = tmp_path / "external.pptx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationship TargetMode="External" Target="https://example.com" />',
        )
    with pytest.raises(OfficeSecurityError, match="External Office relationship"):
        inspect_office_package(path)
