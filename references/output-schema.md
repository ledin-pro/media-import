# Output Schema

The corpus root contains `index.md`, `catalog.md`, `manifest.json`, and mirrored
content Markdown. `originals/` exists only in copy mode.

Every generated content artifact includes source provenance, status, importer
name/version, source hashes when available, original format, and the selected
transcription route for media.

`manifest.json` is the canonical machine state. It records resolved public
configuration without credentials, source identity, every item and status,
owned output hashes, Docling event timing, OCR state, duplicates, warnings,
errors, and validation results.

Visible media Markdown contains no timestamps. Timing remains in each manifest
event under `track.start_time` and `track.end_time`.
