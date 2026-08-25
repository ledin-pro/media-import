# Routing

## Required decisions

Resolve the source, vault root, relative output directory, layout, asset mode,
frame mode, language, OCR language, transcription policy, and existing-output
policy. For ebooks, `inspect` is the inventory stage: after it completes, ask for
one image policy per detected book (`referenced`, `skip`, or `ocr`), naming the
book's `source_path` and planned output. Do not silently use the package default.
Reuse values already present in the request for other decisions.

Defaults are `mirror`, `reference`, `text`, `auto`, `prefer-existing`, and
external processing approved.

## Commands

1. `media-import inspect SOURCE --vault-root PATH --output-dir RELATIVE --json`
2. Read `conflict_groups`, `pdf_preflight`, and `ebooks` from inspect JSON.
3. Ask for and record an image-policy choice for every entry in `ebooks`.
4. For `transcript-needed` groups, run transcript comparison only when the
   batch decision requires it.
5. `media-import import SOURCE ... --dry-run --json`
6. Show one consolidated batch question for all duplicate groups and wait for
   the user's choices.
7. Save conflict choices as `{output_path: source_path}` JSON. Save ebook image
   choices as `{source_path: policy}` JSON and pass that file with
   `--ebook-image-policies-file` to both dry-run and confirmed import.
8. `media-import import SOURCE ... --conflict-decisions FILE --confirmed --json`
9. `media-import validate --output-dir ABSOLUTE_PATH --source SOURCE --json`

Do not add `--confirmed` until the user has seen the current dry-run.

## Failures

- Exit `0`: clean success.
- Exit `1`: completed with warnings.
- Exit `2`: conversion or validation failure.
- Exit `3`: invalid configuration or unavailable dependency.

Keep unsupported, failed, partial, and conflicting items visible in the final report.

The skill orchestrates decisions. `inspect` performs collision grouping, ffprobe
metadata, and PDF preflight. Transcript comparison is the installed
`compare-transcripts` subcommand. These analysis steps do not overwrite Markdown.

Ebook inspect output reports the `docling-ebook` route, planned Markdown and
asset directory, image policy, and MOBI backend. OCR requires a non-empty prompt;
its checkpoint is cache state, not a corpus artifact.
