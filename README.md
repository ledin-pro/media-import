# media-import

`media-import` faithfully converts audio, video, documents, images, local folders,
and direct HTTP(S) media URLs into an Obsidian-compatible Markdown corpus.

Docling is the sole media conversion engine. `pro-ledin-ocr` recognizes visual
text in sampled video frames and image-based documents when needed.

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
