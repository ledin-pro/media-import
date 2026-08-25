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

Referenced ebooks additionally record `asset_dir` and an `assets` array with
corpus-relative paths, SHA-256 hashes, sizes, and media types. These files are
managed outputs: resume and validation check their hashes, and stale cleanup
removes only unchanged owned assets. Ebook OCR checkpoints live under the cache
directory and are recorded for diagnostics, but are not required for corpus
validity after the final Markdown has been written.

Each ebook item records its effective `ebook_image_policy`; when policies differ
within one source tree, the manifest configuration also records the
`source_path`-to-policy mapping.

Visible media Markdown contains no timestamps. Timing remains in each manifest
event under `track.start_time` and `track.end_time`.
