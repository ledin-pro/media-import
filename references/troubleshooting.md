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

## Modified output conflict

The importer does not overwrite an owned artifact whose hash differs from the
previous manifest. Preserve the manual file, move it, or explicitly choose a new
output directory before retrying.
