# Office Conversion

Use Docling's native backends for PDF, DOCX, XLSX, PPTX, images, HTML, Markdown,
CSV, and ODF. Route EPUB, FB2, FB2.ZIP, FBZ, MOBI, AZW, and AZW3 through
`pro-ledin-docling-ebook`. Legacy DOC, XLS, and PPT require explicitly configured
LibreOffice availability. `inspect` reports a per-item `MISSING_SOFFICE`
diagnostic when `soffice`/LibreOffice is unavailable; confirmed imports record
the affected items as `blocked` instead of attempting a conversion.

Before conversion, reject unsafe archive members, excessive expansion, macros,
OLE, ActiveX, remote templates, and path traversal. Never execute embedded code.

Set `office_fallback` or `MEDIA_IMPORT_OFFICE_FALLBACK` to `markitdown`, `pandoc`,
or `auto`. These routes activate only after Docling fails or returns empty output,
and the selected route is recorded in the manifest. Do not create custom Office
parsers in this package.

DOCX, XLSX, and PPTX images are exported through Docling's
`ImageRefMode.REFERENCED` mode into managed `<stem>_artifacts/` files. The
manifest records their paths, SHA-256 hashes, sizes, and media types, and
resume, conflict, stale cleanup, and validation protect those files.

The package fallback ebook image policy is `referenced`, but the skill asks for
an explicit policy per book after inventory. Managed files for `referenced` are
written beside the final Markdown under `<stem>_artifacts/` and recorded with
hashes in the manifest. `skip` omits images. `ocr` stores resumable checkpoints
in the cache and exports recognized text without internal checkpoint metadata.
