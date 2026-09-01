from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .ebook_documents import EBOOK_EXTENSIONS
from .inventory import sha256_file
from .manifest import load_manifest, save_manifest

EMBEDDED_WIKILINK = re.compile(r"!\[\[([^\]|#]+)")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")


def validate_corpus(output_root: Path, source: Path | None = None) -> dict[str, Any]:
    manifest_path = output_root / "manifest.json"
    errors: list[str] = []
    warnings: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
    except ValueError as exc:
        return {"status": "failed", "errors": [str(exc)], "warnings": []}

    seen_outputs: set[str] = set()
    for item in manifest.get("items", []):
        source_path = str(item.get("source_path", ""))
        output_path = item.get("output_path")
        item_status = item.get("status")
        if item_status in {"failed", "conflict"}:
            errors.append(f"{item_status}: {source_path}")
            continue
        if item_status in {"blocked", "partial", "unsupported"}:
            warnings.append(f"{item_status}: {source_path}")
        if item_status in {"blocked", "unsupported", "duplicate", "reused", "removed"}:
            continue
        if not output_path:
            warnings.append(f"No output artifact recorded for {source_path}")
            continue
        if output_path in seen_outputs:
            errors.append(f"Duplicate output path: {output_path}")
            continue
        seen_outputs.add(str(output_path))
        artifact = (output_root / str(output_path)).resolve()
        try:
            artifact.relative_to(output_root.resolve())
        except ValueError:
            errors.append(f"Output escapes corpus root: {output_path}")
            continue
        if not artifact.exists():
            errors.append(f"Missing output artifact: {output_path}")
            continue
        content = artifact.read_text(encoding="utf-8", errors="replace")
        if not content.startswith("---\n") or 'importer: "media-import"' not in content:
            errors.append(f"Invalid media-import frontmatter: {output_path}")
        expected_hash = item.get("output_sha256")
        actual_hash = sha256_file(artifact)
        if expected_hash and expected_hash != actual_hash:
            errors.append(f"Owned output was modified: {output_path}")
        for link in EMBEDDED_WIKILINK.findall(content):
            target = (output_root / link).resolve()
            if not target.is_relative_to(output_root.resolve()) or not target.exists():
                errors.append(f"Broken embedded asset in {output_path}: {link}")
        for link in MARKDOWN_IMAGE.findall(content):
            decoded = unquote(link.strip("<>"))
            if decoded.startswith(("data:", "http://", "https://")):
                continue
            relative_link = Path(decoded)
            if relative_link.is_absolute() or ".." in relative_link.parts:
                errors.append(f"Unsafe Markdown image in {output_path}: {decoded}")
                continue
            target = (artifact.parent / relative_link).resolve()
            if not target.is_relative_to(output_root.resolve()) or not target.exists():
                errors.append(f"Broken Markdown image in {output_path}: {decoded}")
        asset_label = (
            "ebook"
            if any(source_path.casefold().endswith(extension) for extension in EBOOK_EXTENSIONS)
            else "managed"
        )
        for asset in item.get("assets", []):
            asset_path = str(asset.get("path", ""))
            target = (output_root / asset_path).resolve()
            if not target.is_relative_to(output_root.resolve()):
                errors.append(f"{asset_label.capitalize()} asset escapes corpus root: {asset_path}")
                continue
            if not target.is_file():
                errors.append(f"Missing {asset_label} asset: {asset_path}")
                continue
            expected_asset_hash = asset.get("sha256")
            if expected_asset_hash and sha256_file(target) != expected_asset_hash:
                errors.append(f"Owned {asset_label} asset was modified: {asset_path}")

    for required in ("index.md", "catalog.md"):
        if not (output_root / required).exists():
            errors.append(f"Missing corpus index: {required}")

    if source is not None and source.exists():
        source_root = source if source.is_dir() else source.parent
        for item in manifest.get("items", []):
            expected = item.get("source_sha256")
            relative = item.get("source_path")
            if not expected or not relative:
                continue
            if "!/" in str(relative):
                continue
            candidate = source if source.is_file() else source_root / str(relative)
            if candidate.exists() and sha256_file(candidate) != expected:
                errors.append(f"Source changed since import: {relative}")

    status = "failed" if errors else "warning" if warnings else "clean"
    manifest["validation"] = {"status": status, "errors": errors, "warnings": warnings}
    save_manifest(manifest_path, manifest, output_root)
    return {"status": status, "errors": errors, "warnings": warnings}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
