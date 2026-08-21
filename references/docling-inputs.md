# Existing Docling Inputs

Reusable canonical inputs are lossless `DoclingDocument` JSON, DCLX archives
containing a Docling JSON document, associated WebVTT, and manifests written by
this package.

Validate the Docling schema through `DoclingDocument.model_validate`. Preserve
item hierarchy, source identity, pictures, and `TrackSource`. Reject ambiguous
associations. Other derived-package layouts are unsupported in the first release.
