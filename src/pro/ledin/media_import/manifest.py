from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import atomic_write

SCHEMA_VERSION = 1


def new_manifest(config: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "importer": "media-import",
        "importer_version": "0.1.0",
        "created_at": now,
        "updated_at": now,
        "config": config,
        "source": source,
        "items": [],
        "duplicates": [],
        "validation": {"status": "pending", "errors": [], "warnings": []},
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported manifest schema in {path}")
    return value


def save_manifest(path: Path, manifest: dict[str, Any], output_root: Path) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    atomic_write(
        path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        [output_root],
    )


def status_counts(manifest: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(str(item.get("status", "unknown")) for item in manifest.get("items", [])))
