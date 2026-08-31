from __future__ import annotations

import json
import shutil
import subprocess
import unicodedata
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Any

from .config import EBOOK_FORMAT_PREFERENCE
from .inventory import SourceItem
from .paths import safe_stem

EBOOK_EXTENSIONS = {f".{format_name}" for format_name in EBOOK_FORMAT_PREFERENCE}
EBOOK_VARIANT_WARNING = (
    "Ebook variant content was not compared; canonical source was selected by format preference."
)


def normalized_output_path(relative_path: str) -> str:
    source = Path(relative_path)
    parts = [safe_stem(part) for part in source.parts[:-1]]
    stem = safe_stem(source.stem)
    return "/".join((*parts, f"{stem}.md"))


def _ebook_format_preference(preference: tuple[str, ...] | None) -> tuple[str, ...]:
    selected = preference or EBOOK_FORMAT_PREFERENCE
    normalized = tuple(value.casefold().lstrip(".") for value in selected)
    return normalized + tuple(
        value for value in EBOOK_FORMAT_PREFERENCE if value not in normalized
    )


def _ebook_variant_key(item: SourceItem) -> tuple[str, str] | None:
    if item.extension.casefold() not in EBOOK_EXTENSIONS:
        return None
    path = Path(item.source_path)
    extension = item.extension.casefold()
    if not path.name.casefold().endswith(extension):
        return None
    basename = path.name[: -len(extension)]
    normalized_basename = unicodedata.normalize("NFC", basename).casefold()
    if not normalized_basename:
        return None
    return path.parent.as_posix(), normalized_basename


def ebook_variant_groups(
    items: list[SourceItem],
    preference: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[SourceItem]] = defaultdict(list)
    for item in items:
        key = _ebook_variant_key(item)
        if key is not None:
            groups[key].append(item)

    ordered_preference = _ebook_format_preference(preference)
    format_ranks = {value: index for index, value in enumerate(ordered_preference)}
    result: list[dict[str, Any]] = []
    for (directory, basename), group in sorted(groups.items()):
        if len(group) < 2:
            continue
        canonical = min(
            group,
            key=lambda item: (
                format_ranks.get(item.extension.casefold().lstrip("."), len(format_ranks)),
                item.source_path.casefold(),
            ),
        )
        alternatives = sorted(
            (item.source_path for item in group if item.source_path != canonical.source_path),
            key=str.casefold,
        )
        result.append(
            {
                "source_directory": directory,
                "normalized_basename": basename,
                "reason": "ebook-variant",
                "canonical_source_path": canonical.source_path,
                "canonical_source": canonical.source_path,
                "skipped_alternatives": alternatives,
                "content_compared": False,
                "warning": EBOOK_VARIANT_WARNING,
            }
        )
    return result


def ebook_variant_aliases(groups: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(alternative): str(group["canonical_source_path"])
        for group in groups
        for alternative in group.get("skipped_alternatives", [])
    }


def _probe_media(item: SourceItem) -> dict[str, Any]:
    if item.absolute_path is None or item.kind != "media":
        return {}
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {"metadata_error": "ffprobe is not installed"}
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of",
        "json",
        str(item.absolute_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            return {"metadata_error": (completed.stderr or "ffprobe failed").strip()}
        data = json.loads(completed.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"metadata_error": str(exc)}
    streams = data.get("streams") or []
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    duration = (data.get("format") or {}).get("duration")
    result: dict[str, Any] = {}
    if duration is not None:
        with suppress(TypeError, ValueError):
            result["duration_seconds"] = round(float(duration), 3)
    for key in ("codec_name", "sample_rate", "channels"):
        if key in audio:
            result[key] = audio[key]
    return result


def analyze_conflicts(
    items: list[SourceItem],
    candidate_paths: dict[str, str],
    *,
    existing_manifest: dict[str, Any] | None = None,
    output_root: Path | None = None,
    ignored_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[SourceItem]] = defaultdict(list)
    ignored = ignored_sources or set()
    for item in items:
        if item.source_path in ignored:
            continue
        candidate = candidate_paths.get(item.source_path, normalized_output_path(item.source_path))
        groups[candidate].append(item)

    previous_items = (existing_manifest or {}).get("items", [])
    previous_by_output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in previous_items:
        output_path = record.get("output_path")
        if output_path:
            previous_by_output[str(output_path)].append(record)

    result: list[dict[str, Any]] = []
    for output_path, group in sorted(groups.items()):
        unique_items: list[SourceItem] = []
        canonical_by_hash: dict[str, SourceItem] = {}
        automatic_duplicates: list[dict[str, str]] = []
        for item in group:
            identity = item.sha256 or item.source_path
            canonical = canonical_by_hash.get(identity)
            if canonical is None:
                canonical_by_hash[identity] = item
                unique_items.append(item)
            else:
                automatic_duplicates.append(
                    {
                        "source_path": item.source_path,
                        "canonical_source_path": canonical.source_path,
                    }
                )
        owners = previous_by_output.get(output_path, [])
        changed = []
        if output_root is not None:
            for owner in owners:
                output = output_root / output_path
                expected = owner.get("output_sha256")
                if expected and output.exists():
                    from .inventory import sha256_file

                    if sha256_file(output) != expected:
                        changed.append(str(owner.get("source_path", "")))
        group_sources = {item.source_path for item in unique_items}
        owner_sources = {str(owner.get("source_path", "")) for owner in owners}
        ownership_collision = bool(owner_sources - group_sources)
        if len(unique_items) < 2 and not changed and not ownership_collision:
            continue
        kinds = {item.kind for item in unique_items}
        media_group = kinds == {"media"}
        if changed:
            reason = "manual-edit"
        elif len(unique_items) > 1 and media_group:
            reason = "same-basename"
        elif len(unique_items) > 1:
            reason = "non-media-collision"
        else:
            reason = "existing-output"
        entries = []
        for item in unique_items:
            entry = item.public_dict()
            entry.update(_probe_media(item))
            entries.append(entry)
        if media_group and (len(unique_items) > 1 or ownership_collision):
            analysis_status = "transcript-needed"
        elif changed:
            analysis_status = "manual-edit"
        else:
            analysis_status = "metadata-only"
        result.append(
            {
                "output_path": output_path,
                "reason": reason,
                "analysis_status": analysis_status,
                "analysis_mode": "metadata-only",
                "items": entries,
                "automatic_duplicates": automatic_duplicates,
                "existing_owners": owners,
                "modified_owners": changed,
            }
        )
    return result


def collision_safe_path(candidate: str, item: SourceItem) -> str:
    path = Path(candidate)
    identity = item.sha256 or item.source_path
    suffix = item.extension.lstrip(".") or item.kind
    return path.with_name(f"{path.stem}-{safe_stem(suffix)}-{identity[:8]}.md").as_posix()


def build_output_plan(
    items: list[SourceItem],
    candidate_paths: dict[str, str],
    decisions: dict[str, str],
    duplicate_aliases: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    groups: dict[str, list[SourceItem]] = defaultdict(list)
    for item in items:
        if item.source_path in duplicate_aliases or item.kind == "unsupported":
            continue
        groups[candidate_paths[item.source_path]].append(item)

    output_paths: dict[str, str] = {}
    canonical_aliases: dict[str, str] = {}
    unresolved: list[str] = []
    for candidate, group in groups.items():
        if len(group) == 1:
            output_paths[group[0].source_path] = candidate
            continue
        if {item.kind for item in group} != {"media"}:
            for item in group:
                output_paths[item.source_path] = collision_safe_path(candidate, item)
            continue
        selected = decisions.get(candidate)
        source_paths = {item.source_path for item in group}
        if selected not in source_paths:
            unresolved.append(candidate)
            continue
        output_paths[selected] = candidate
        for item in group:
            if item.source_path != selected:
                canonical_aliases[item.source_path] = selected
    return output_paths, canonical_aliases, sorted(unresolved)
