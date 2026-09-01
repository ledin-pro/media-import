# Troubleshooting

## Missing Docling

Run `uv sync` and confirm `uv run python -c "import docling"` succeeds. Current
releases expose video dependencies through `docling-slim[format-video]`, not a
`format-video` extra on the `docling` wrapper package.

## Missing ffmpeg

Install both `ffmpeg` and `ffprobe`, then rerun `inspect`.

## Missing OCR engine

Set `MEDIA_IMPORT_OCR_ENGINE` to a supported `pro-ledin-ocr` engine. Vision OCR
also requires the API key and model; external processing is approved by default.

## Apple Silicon MLX

Use provider `auto` to let Docling select MLX when installed, or `docling-mlx`
to require it. Forced MLX fails preflight on non-Apple-Silicon systems.

## Missing GigaAM provider

Install `docling-gigaam>=0.1,<0.2` and rerun `inspect`. Development checkouts use
the sibling `../docling-gigaam` source configured in `pyproject.toml`. Preflight
checks package and PyTorch runtime availability without importing the provider or
downloading a model.

GigaAM v3 transcribes Russian only. Use `auto`, `ru`, `rus`, or `russian`; other
explicit languages are rejected during configuration. The first confirmed
conversion downloads the checksum-verified official model into the media-import
cache. Long recordings use local Silero processing and no API token is required.

On Apple Silicon, `MEDIA_IMPORT_DOCLING_DEVICE=mps` is allowed with a warning:
unsupported GigaAM or Silero operations may execute on CPU. The `mlx` device is
not supported by this provider.

## Modified output conflict

The importer does not overwrite an owned artifact whose hash differs from the
previous manifest. Preserve the manual file, move it, or explicitly choose a new
output directory before retrying.

## Missing ebook backend

Install `pro-ledin-docling-ebook>=0.2,<0.3` and rerun `inspect`. EPUB and FB2
families need no external converter. MOBI, AZW, and AZW3 require `mobitool` or
Calibre `ebook-convert`; `MEDIA_IMPORT_EBOOK_MOBI_BACKEND` can select one.

Referenced ebook assets are owned individually through manifest hashes. Missing
assets are regenerated, but modified assets produce a conflict and are never
overwritten or removed. Ebook OCR requires a prompt plus vision URL, key, model,
and external-processing approval. Use `MEDIA_IMPORT_EBOOK_RESTART_OCR=true` only
when intentionally discarding an incompatible OCR checkpoint.

## Missing LibreOffice

Legacy `.doc`, `.xls`, and `.ppt` items require the `soffice` executable. Install
LibreOffice and rerun `inspect`; missing availability is reported per item as
`MISSING_SOFFICE`, and confirmed imports block those items without writing an
artifact. Modern DOCX/XLSX/PPTX files do not require LibreOffice and export
Docling images as managed referenced assets.
