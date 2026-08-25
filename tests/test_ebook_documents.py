from pathlib import Path

from ebook_helpers import make_fb2
from pro.ledin.docling_ebook import OcrImageResult

from pro.ledin.media_import.config import Config
from pro.ledin.media_import.ebook_documents import convert_ebook_document


def _config(tmp_path: Path, policy: str) -> Config:
    return Config(
        source=str(tmp_path / "book.fb2"),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy=policy,
    )


def test_referenced_ebook_returns_managed_asset_payloads(tmp_path: Path) -> None:
    source = tmp_path / "book.fb2"
    make_fb2(source)
    output_root = tmp_path / "vault/corpus"
    output_path = output_root / "book.md"

    body, document, details = convert_ebook_document(
        source, _config(tmp_path, "referenced"), output_path, output_root
    )

    assert document.name == "Test Book"
    assert "book_artifacts/cover.png" in body
    assert details["conversion_route"] == "docling-ebook"
    assert details["assets"][0]["path"] == "book_artifacts/cover.png"
    assert details["_asset_payloads"][0]["data"].startswith(b"\x89PNG")


def test_skip_ebook_has_no_asset_payloads(tmp_path: Path) -> None:
    source = tmp_path / "book.fb2"
    make_fb2(source)
    output_root = tmp_path / "vault/corpus"

    body, document, details = convert_ebook_document(
        source,
        _config(tmp_path, "skip"),
        output_root / "book.md",
        output_root,
    )

    assert "Hello book." in body
    assert not document.pictures
    assert details["assets"] == []


def test_ocr_ebook_uses_resumable_transform(tmp_path: Path, monkeypatch) -> None:
    import pro.ledin.docling_ebook

    source = tmp_path / "book.fb2"
    make_fb2(source)
    output_root = tmp_path / "vault/corpus"

    class Callback:
        configuration_fingerprint = "test-callback"

        def recognize(self, request):
            return OcrImageResult(text=f"Recognized {request.filename}")

    monkeypatch.setattr(
        pro.ledin.docling_ebook,
        "load_ocr_callback",
        lambda *args, **kwargs: Callback(),
    )
    config = Config(
        source=str(source),
        vault_root=tmp_path / "vault",
        output_dir=Path("corpus"),
        cache_dir=tmp_path / "cache",
        ebook_image_policy="ocr",
        ebook_ocr_prompt="Read the image",
        ebook_ocr_callback="test:callback",
    )

    body, document, details = convert_ebook_document(
        source, config, output_root / "book.md", output_root
    )

    assert "Recognized cover.png" in body
    assert not document.pictures
    assert details["ocr_status"] == "completed"
    assert Path(details["ocr_checkpoint"]).is_file()
