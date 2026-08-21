from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


class DoclingImportError(ValueError):
    """Raised when a canonical Docling export is invalid."""


def _load_dict(path: Path) -> dict[str, Any]:
    if path.suffix.casefold() == ".dclx":
        try:
            with zipfile.ZipFile(path) as archive:
                candidates = [
                    name for name in archive.namelist() if name.casefold().endswith(".json")
                ]
                if not candidates:
                    raise DoclingImportError("DCLX archive contains no JSON document")
                value = json.loads(archive.read(sorted(candidates)[0]).decode("utf-8"))
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise DoclingImportError(f"Cannot read DCLX export: {exc}") from exc
    else:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DoclingImportError(f"Cannot read Docling JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DoclingImportError("Docling export must contain a JSON object")
    return value


def load_docling_document(path: Path) -> Any:
    from docling_core.types.doc import DoclingDocument

    try:
        return DoclingDocument.model_validate(_load_dict(path))
    except Exception as exc:
        raise DoclingImportError(f"Invalid DoclingDocument export: {exc}") from exc
