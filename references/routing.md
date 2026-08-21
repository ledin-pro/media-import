# Routing

## Required decisions

Resolve the source, vault root, relative output directory, layout, asset mode,
frame mode, language, OCR language, transcription policy, and existing-output
policy. Reuse values already present in the request.

Defaults are `mirror`, `reference`, `text`, `auto`, `prefer-existing`, and
external processing approved.

## Commands

1. `media-import inspect SOURCE --vault-root PATH --output-dir RELATIVE --json`
2. `media-import import SOURCE ... --dry-run --json`
3. Show the plan and wait for confirmation.
4. `media-import import SOURCE ... --confirmed --json`
5. `media-import validate --output-dir ABSOLUTE_PATH --source SOURCE --json`

Do not add `--confirmed` until the user has seen the current dry-run.

## Failures

- Exit `0`: clean success.
- Exit `1`: completed with warnings.
- Exit `2`: conversion or validation failure.
- Exit `3`: invalid configuration or unavailable dependency.

Keep unsupported, failed, partial, and conflicting items visible in the final report.
