# Conflict Triage

`media-import inspect --json` reports collision groups without changing files.
The skill reads this JSON and asks one batch question when a canonical source
must be selected.

## Categories

- `same-basename`: multiple media sources resolve to one Markdown path.
- `non-media-collision`: different content types, such as `.pdf` and `.mov`,
  resolve to one path. Never merge these automatically.
- `manual-edit`: an importer-owned output no longer matches its manifest hash.
- `existing-output`: a prior output exists but no current source group explains it.

## Transcript Comparison

Use `media-import compare-transcripts A B --json` after producing transcripts for both sides.
It reports word coverage in both directions. These are heuristics, not proof of
bit-identical audio:

- `full-equivalent`: both coverage values are at least `0.95`.
- `partial-variant`: canonical coverage is at least `0.75` and variant coverage
  is at least `0.90`.
- `different`: lower coverage or clearly different material.

If the result is equivalent or partial, the skill must still ask the user in one
batch question which source is canonical, which is especially important when one
recording is longer.

## Encrypted PDFs

`inspect` includes `pdf_preflight` for PDF files and uses qpdf when available:

1. Restrictions-only encryption: create a temporary decrypted copy with qpdf,
   OCR it, then delete the copy. Never modify the source.
2. Password required: mark `blocked` and ask for an unlocked copy.
3. Failed decryption: retain the diagnostic and offer manual/visual handoff.

Never brute-force or bypass unknown PDF passwords.

## Batch Decision

The decision file is a JSON object mapping each reported `output_path` to the
chosen canonical `source_path`. The importer marks other media in the group as
duplicates. Mixed content types receive separate deterministic paths automatically.

Do not use `--force` to resolve these groups. It can overwrite one source's
transcript with another source's transcript.
