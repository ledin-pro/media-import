# Office Conversion

Use Docling's native backends for PDF, DOCX, XLSX, PPTX, images, HTML, Markdown,
CSV, EPUB, and ODF. Legacy DOC, XLS, and PPT require explicitly configured
LibreOffice availability.

Before conversion, reject unsafe archive members, excessive expansion, macros,
OLE, ActiveX, remote templates, and path traversal. Never execute embedded code.

Set `office_fallback` or `MEDIA_IMPORT_OFFICE_FALLBACK` to `markitdown`, `pandoc`,
or `auto`. These routes activate only after Docling fails or returns empty output,
and the selected route is recorded in the manifest. Do not create custom Office
parsers in this package.
