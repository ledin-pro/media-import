# Routing

## Required decisions

Resolve the source, vault root, relative output directory, layout, asset mode,
frame mode, language, OCR language, transcription policy, and existing-output
policy. Reuse values already present in the request.

Defaults are `mirror`, `reference`, `text`, `auto`, `prefer-existing`, and
external processing approved.

## Commands

1. `media-import inspect SOURCE --vault-root PATH --output-dir RELATIVE --json`
2. Read `conflict_groups` and `pdf_preflight` from inspect JSON.
3. For `transcript-needed` groups, run transcript comparison only when the
   batch decision requires it.
4. `media-import import SOURCE ... --dry-run --json`
5. Show one consolidated batch question for all duplicate groups and wait for
   the user's choices.
6. Save the choices as `{output_path: source_path}` JSON.
7. `media-import import SOURCE ... --conflict-decisions FILE --confirmed --json`
8. `media-import validate --output-dir ABSOLUTE_PATH --source SOURCE --json`

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
