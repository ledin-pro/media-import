# media-import

`media-import` faithfully converts audio, video, documents, images, local folders,
and direct HTTP(S) media URLs into an Obsidian-compatible Markdown corpus.

Docling is the sole media conversion engine. `pro-ledin-ocr` recognizes visual
text in sampled video frames and image-based documents when needed.

`pro-ledin-docling-ebook` converts EPUB, FB2, FB2.ZIP, FBZ, MOBI, AZW, and AZW3
into native Docling documents. Ebook images can be referenced, skipped, or
replaced with resumable OCR text.

Whisper Turbo remains the default transcription route. Russian audio and video
can optionally use the local GigaAM v3 provider supplied by `docling-gigaam`.

## Install

Install the published package and verify the CLI:

```bash
python -m pip install pro-ledin-media-import
media-import --help
```

On macOS, install the system video dependencies separately:

```bash
brew install ffmpeg
ffmpeg -version
ffprobe -version
```

## Install for development

```bash
uv sync --extra dev
uv run media-import --help
```

The development configuration resolves `docling-gigaam` and
`pro-ledin-docling-ebook` from sibling checkouts. Published installations can
install them explicitly:

```bash
python -m pip install 'docling-gigaam>=0.1,<0.2' 'pro-ledin-docling-ebook>=0.2,<0.3'
```

The published `docling` package supplies standard document support, while
`docling-slim[format-video]` supplies the current video/ASR dependencies.
Docling media conversion also requires `ffmpeg` and `ffprobe`. Model downloads
are never started by `inspect` or `--dry-run`.

## Workflow

```bash
uv run media-import inspect ./recordings --vault-root ~/vault --output-dir sources/demo
uv run media-import import ./recordings --vault-root ~/vault --output-dir sources/demo --dry-run
uv run media-import import ./recordings --vault-root ~/vault --output-dir sources/demo --confirmed
uv run media-import validate --output-dir ~/vault/sources/demo --source ./recordings
uv run media-import status --output-dir ~/vault/sources/demo
```

The first real import requires the exact dry-run plan to have been confirmed by
the caller with `--confirmed`. An OpenCode agent should show the dry-run to the
user before adding this flag.

## Configuration

CLI arguments override environment variables, which override `config.json`.
See `config.example.json` and `references/routing.md`.

The canonical environment prefix is `MEDIA_IMPORT_`. Credentials are never
written to the manifest or included in cache-profile hashes.

To transcribe Russian media with GigaAM v3:

```bash
MEDIA_IMPORT_TRANSCRIPTION_PROVIDER=gigaam \
MEDIA_IMPORT_LANGUAGE=ru \
media-import inspect ./recordings --vault-root ~/vault --output-dir sources/demo
```

When no transcription model is explicitly configured, provider `gigaam` uses
`v3_e2e_rnnt`; every other provider keeps the `whisper_turbo` default. GigaAM v3
accepts `auto`, `ru`, `rus`, or `russian` and rejects other explicit languages.
The checksum-verified official model downloads into the media-import cache on
first real conversion. Long recordings use local Silero long-form processing.
No API token is required.

Ebooks default to referenced images:

```bash
media-import inspect ./books --vault-root ~/vault --output-dir sources/books \
  --ebook-image-policy referenced
```

Use `--ebook-image-policy skip` to omit images. Use `ocr` to replace each image
occurrence with recognized text; OCR requires `--ebook-ocr-prompt` (or prompt
file), vision endpoint credentials, and explicit external-processing approval.
MOBI/AZW/AZW3 additionally require `mobitool` or Calibre `ebook-convert`.
