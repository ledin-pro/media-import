from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .archives import download_archive, extract_archive, inspect_archive
from .config import Config, ConfigError, load_config
from .conflicts import analyze_conflicts, build_output_plan, normalized_output_path
from .dedupe import exact_duplicate_groups, normalized_text_hash
from .docling_adapter import DocumentEvent, Track, iter_events
from .docling_documents import convert_document, export_markdown
from .docling_imports import load_docling_document
from .docling_media import convert_media, release_media_memory
from .environment import has_errors, run_preflight
from .inventory import SourceItem, inventory, sha256_file
from .manifest import load_manifest, new_manifest, save_manifest, status_counts
from .markdown import render_document_markdown, render_media_markdown, title_from_path
from .paths import atomic_write, output_path_for
from .pdf_preflight import PdfPasswordRequired, inspect_pdf_encryption
from .progress import ProgressReporter
from .sources import resolve_source
from .transcript_compare import compare_transcripts
from .validate import validate_corpus
from .visual_text import recognize_picture, save_picture

VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
VTT_TIMING = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+"
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media-import")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("inspect", "import"):
        child = subparsers.add_parser(command)
        child.add_argument("source")
        child.add_argument("--vault-root", type=Path)
        child.add_argument("--output-dir", type=Path)
        child.add_argument("--config", type=Path)
        child.add_argument("--cache-dir", type=Path)
        child.add_argument("--asset-mode", choices=["reference", "copy"])
        child.add_argument("--frame-mode", choices=["none", "text", "text-and-images", "images"])
        child.add_argument("--layout", choices=["mirror", "mapped"])
        child.add_argument("--language")
        child.add_argument("--ocr-language")
        child.add_argument(
            "--transcription-policy", choices=["prefer-existing", "missing", "force"]
        )
        child.add_argument(
            "--transcription-provider",
            choices=["auto", "existing", "docling-mlx", "docling-native", "gigaam", "off"],
        )
        child.add_argument("--jobs", type=int)
        child.add_argument("--json", action="store_true", dest="json_output")
        child.add_argument("--verbose", action="store_true")
        if command == "import":
            child.add_argument("--dry-run", action="store_true")
            child.add_argument("--confirmed", action="store_true")
            child.add_argument("--resume", action="store_true")
            child.add_argument("--fail-on-warning", action="store_true")
            child.add_argument("--only", default="media,documents,indexes")
            child.add_argument("--conflict-decisions", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--output-dir", type=Path, required=True)
    validate.add_argument("--source", type=Path)
    validate.add_argument("--json", action="store_true", dest="json_output")

    status = subparsers.add_parser("status")
    status.add_argument("--output-dir", type=Path, required=True)
    status.add_argument("--json", action="store_true", dest="json_output")
    compare = subparsers.add_parser("compare-transcripts")
    compare.add_argument("canonical", type=Path)
    compare.add_argument("variant", type=Path)
    compare.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    names = (
        "source",
        "vault_root",
        "output_dir",
        "cache_dir",
        "asset_mode",
        "frame_mode",
        "layout",
        "language",
        "ocr_language",
        "transcription_policy",
        "transcription_provider",
        "jobs",
        "verbose",
    )
    return {name: getattr(args, name, None) for name in names}


def _emit(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "message" in value:
        print(value["message"])
    for key, item in value.items():
        if key == "message":
            continue
        print(f"{key}: {json.dumps(item, ensure_ascii=False, sort_keys=True)}")


def _inspect(
    config: Config,
    *,
    for_import: bool,
    progress: ProgressReporter | None = None,
) -> tuple[dict[str, Any], list[SourceItem]]:
    source = resolve_source(config.source)
    items = inventory(source, progress)
    diagnostics = run_preflight(config, items, for_import=for_import)
    counts = Counter(item.kind for item in items)
    candidate_paths = {
        item.source_path: normalized_output_path(_output_source_path(item, config))
        for item in items
    }
    manifest: dict[str, Any] | None = None
    manifest_path = config.output_root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = load_manifest(manifest_path)
        except ValueError:
            manifest = None
    pdf_preflight = {
        item.source_path: inspect_pdf_encryption(item.absolute_path)
        for item in items
        if item.extension == ".pdf" and item.absolute_path is not None
    }
    associated_vtt = {
        vtt.source_path
        for media in items
        if media.kind == "media"
        for vtt in [_matching_vtt(media, items)]
        if vtt is not None and config.transcription_policy != "force"
    }
    archive_summaries: dict[str, Any] = {}
    for item in items:
        if item.kind == "archive" and item.absolute_path:
            try:
                summary = inspect_archive(item.absolute_path)
                archive_summaries[item.source_path] = summary.public_dict()
            except ValueError as exc:
                archive_summaries[item.source_path] = {"error": str(exc)}
    result = {
        "source": {
            "kind": source.kind,
            "path": str(source.local_path) if source.local_path else None,
            "uri": source.source_uri,
        },
        "destination": str(config.output_root),
        "counts": dict(sorted(counts.items())),
        "items": [item.public_dict() for item in items],
        "duplicates": exact_duplicate_groups(items),
        "archives": archive_summaries,
        "diagnostics": [item.public_dict() for item in diagnostics],
        "would_write": ["index.md", "catalog.md", "manifest.json"],
        "existing_output": _inspect_existing_output(config, items),
        "conflict_groups": analyze_conflicts(
            items,
            candidate_paths,
            existing_manifest=manifest,
            output_root=config.output_root,
            ignored_sources=associated_vtt,
        ),
        "pdf_preflight": pdf_preflight,
    }
    return result, items


def _load_conflict_decisions(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Invalid conflict decisions file: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in data.items()
    ):
        raise ConfigError("Conflict decisions must be a JSON object of output path to source path")
    return data


def _inspect_existing_output(config: Config, items: list[SourceItem]) -> dict[str, Any]:
    manifest_path = config.output_root / "manifest.json"
    if not manifest_path.exists():
        return {"manifest": False, "changes": [], "conflicts": [], "stale": []}
    try:
        manifest = load_manifest(manifest_path)
    except ValueError as exc:
        return {"manifest": True, "error": str(exc)}
    previous = {str(item.get("source_path")): item for item in manifest.get("items", [])}
    changes: list[str] = []
    conflicts: list[str] = []
    current = {item.source_path for item in items}
    for item in items:
        old = previous.get(item.source_path)
        if old and old.get("source_sha256") != item.sha256:
            changes.append(item.source_path)
        if old and old.get("output_path") and old.get("output_sha256"):
            output = config.output_root / str(old["output_path"])
            if output.exists() and sha256_file(output) != old["output_sha256"]:
                conflicts.append(item.source_path)
    return {
        "manifest": True,
        "changes": sorted(changes),
        "conflicts": sorted(conflicts),
        "stale": sorted(path for path in previous if path not in current),
    }


def _expand_archives(
    items: list[SourceItem], config: Config, progress: ProgressReporter | None = None
) -> list[SourceItem]:
    expanded: list[SourceItem] = []
    for item in items:
        if item.kind != "archive":
            expanded.append(item)
            continue
        identity = item.sha256 or hashlib.sha256(item.source_path.encode()).hexdigest()
        archive_path = item.absolute_path
        if archive_path is None:
            if item.source_uri is None:
                raise ValueError(f"Archive has no source: {item.source_path}")
            archive_path = download_archive(
                item.source_uri,
                config.cache_dir / "downloads" / f"{identity}{item.extension}",
            )
        destination = config.cache_dir / "archives" / identity
        if progress:
            progress.emit("archive", "start", source=item.source_path)
        if not destination.exists():
            extract_archive(archive_path, destination)
        children = inventory(resolve_source(str(destination)), progress)
        if progress:
            progress.emit("archive", "complete", source=item.source_path, items=len(children))
        expanded.extend(
            replace(child, source_path=f"{item.source_path}!/{child.source_path}")
            for child in children
        )
    return expanded


def _source_value(item: SourceItem) -> Path | str:
    if item.absolute_path is not None:
        return item.absolute_path
    if item.source_uri is not None:
        return item.source_uri
    raise ValueError(f"Item has no source: {item.source_path}")


def _output_source_path(item: SourceItem, config: Config) -> str:
    if config.layout == "mirror":
        return item.source_path
    matches = [
        (source, destination)
        for source, destination in config.path_map.items()
        if item.source_path == source or item.source_path.startswith(f"{source}/")
    ]
    if not matches:
        raise ConfigError(f"No path_map entry matches source path: {item.source_path}")
    source, destination = max(matches, key=lambda pair: len(pair[0]))
    suffix = item.source_path[len(source) :].lstrip("/")
    return "/".join(part for part in (destination, suffix) if part)


def _metadata(item: SourceItem, config: Config, status: str, content_kind: str) -> dict[str, Any]:
    return {
        "type": "source",
        "source": Path(config.source).name or config.source,
        "content_kind": content_kind,
        "source_path": item.source_path if not item.source_uri else None,
        "source_uri": item.source_uri,
        "source_paths": [item.source_path],
        "source_hashes": [f"sha256:{item.sha256}"] if item.sha256 else [],
        "status": status,
        "language": config.transcription_language,
        "importer": "media-import",
        "importer_version": "0.1.0",
        "transcription_provider": config.transcription_provider
        if content_kind == "media_transcript"
        else None,
        "transcription_model": config.transcription_model
        if content_kind == "media_transcript"
        else None,
        "original_format": item.extension.lstrip("."),
    }


def _vtt_events(path: Path) -> list[DocumentEvent]:
    events: list[DocumentEvent] = []
    cue: list[str] = []
    index = 0
    pending_track: Track | None = None

    def seconds(hours: str | None, minutes: str, secs: str, millis: str) -> float:
        return int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        line = raw.strip()
        if "-->" in line:
            match = VTT_TIMING.search(line)
            if match:
                values = match.groups()
                pending_track = Track(
                    seconds(values[0], values[1], values[2], values[3]),
                    seconds(values[4], values[5], values[6], values[7]),
                    None,
                )
            continue
        if not line:
            if cue:
                text = " ".join(cue).strip()
                if text and text.casefold() != "webvtt":
                    events.append(DocumentEvent(f"vtt-{index}", "text", text, pending_track, None))
                    index += 1
                cue.clear()
                pending_track = None
            continue
        if line.isdigit() or line.casefold() == "webvtt":
            continue
        cue.append(line)
    return events


def _matching_vtt(item: SourceItem, items: list[SourceItem]) -> SourceItem | None:
    stem = Path(item.source_path).with_suffix("")
    for candidate in items:
        if candidate.extension == ".vtt" and Path(candidate.source_path).with_suffix("") == stem:
            return candidate
    return None


def _conversion_status(result: Any) -> tuple[str, list[str]]:
    status_value = str(getattr(result, "status", "success")).casefold()
    errors = [
        str(getattr(error, "error_message", error)) for error in getattr(result, "errors", [])
    ]
    if "failure" in status_value:
        return "failed", errors
    if "partial" in status_value or errors:
        return "partial", errors
    return "complete", errors


def _cache_docling(
    document: Any,
    item: SourceItem,
    config: Config,
    *,
    exclude_images: bool = False,
) -> str | None:
    identity = item.sha256 or hashlib.sha256(item.source_path.encode()).hexdigest()
    path = config.cache_dir / "docling" / f"{identity}.json"
    try:
        if exclude_images and hasattr(document, "model_dump"):
            data = document.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                exclude={"pictures": {"__all__": {"image"}}},
            )
        else:
            data = document.export_to_dict()
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except Exception:
        return None
    atomic_write(path, payload + "\n", [config.cache_dir])
    return str(path)


def _process_item(
    item: SourceItem,
    items: list[SourceItem],
    config: Config,
    output_root: Path,
    progress: ProgressReporter | None = None,
) -> tuple[str, dict[str, Any]]:
    title = title_from_path(item.source_path)
    visual_results: dict[str, dict[str, Any]] = {}
    events: list[DocumentEvent] = []
    errors: list[str] = []
    cache_path: str | None = None

    if item.kind == "media":
        vtt = _matching_vtt(item, items)
        use_vtt = vtt is not None and config.transcription_policy != "force"
        if use_vtt and vtt and vtt.absolute_path:
            events = _vtt_events(vtt.absolute_path)
            status = "complete"
            provider = "existing"
            if progress:
                progress.emit(
                    "transcription",
                    "complete",
                    result="reused",
                    source=item.source_path,
                    provider=provider,
                )
        elif config.transcription_provider in {"existing", "off"}:
            events = []
            status = "partial"
            provider = config.transcription_provider
            errors.append("No reusable transcript is available and ASR is disabled")
            if progress:
                progress.emit(
                    "transcription",
                    "complete",
                    result="partial",
                    source=item.source_path,
                    provider=provider,
                )
        else:
            started = time.monotonic()
            if progress:
                progress.emit(
                    "transcription",
                    "start",
                    source=item.source_path,
                    provider=config.transcription_provider,
                )
            try:
                result = convert_media(_source_value(item), config, item.extension)
            except Exception:
                if progress:
                    progress.emit(
                        "transcription",
                        "failed",
                        source=item.source_path,
                        elapsed=f"{time.monotonic() - started:.1f}s",
                    )
                raise
            status, errors = _conversion_status(result)
            document = result.document
            events = list(iter_events(document))
            cache_path = _cache_docling(
                document,
                item,
                config,
                exclude_images=item.extension in VIDEO_EXTENSIONS,
            )
            provider = config.transcription_provider
            if progress:
                progress.emit(
                    "transcription",
                    "complete",
                    result=status,
                    source=item.source_path,
                    provider=provider,
                    elapsed=f"{time.monotonic() - started:.1f}s",
                )
            if item.extension in VIDEO_EXTENSIONS:
                for event in events:
                    if event.kind != "picture":
                        continue
                    visual: dict[str, Any] = {}
                    if config.frame_mode in {"text-and-images", "images"}:
                        identity = (
                            item.sha256 or hashlib.sha256(item.source_path.encode()).hexdigest()
                        )
                        event_hash = hashlib.sha256(event.event_id.encode()).hexdigest()[:12]
                        image_relative = (
                            Path("assets")
                            / f"{Path(item.source_path).stem}-{identity[:8]}"
                            / f"{event_hash}.png"
                        )
                        save_picture(
                            document,
                            event.item,
                            output_root / image_relative,
                            output_root,
                        )
                        visual["image_path"] = image_relative.as_posix()
                    if config.frame_mode in {"text", "text-and-images"}:
                        ocr_started = time.monotonic()
                        if progress:
                            progress.emit(
                                "ocr",
                                "start",
                                detail=True,
                                source=item.source_path,
                                frame=event.event_id,
                                engine=config.ocr_engine or "default",
                            )
                        visual.update(recognize_picture(document, event.item, config))
                        if progress:
                            progress.emit(
                                "ocr",
                                "complete",
                                detail=True,
                                source=item.source_path,
                                frame=event.event_id,
                                elapsed=f"{time.monotonic() - ocr_started:.1f}s",
                            )
                    visual_results[event.event_id] = visual
        metadata = _metadata(item, config, status, "media_transcript")
        metadata["transcription_provider"] = provider
        text = render_media_markdown(
            title=title,
            metadata=metadata,
            events=events,
            visual_text=visual_results,
        )
        details = {
            "status": status,
            "errors": errors,
            "transcription_provider": provider,
            "transcription_model": config.transcription_model,
            "events": [event.manifest_dict() for event in events],
            "frame_count": sum(event.kind == "picture" for event in events),
            "frames_with_text": sum(bool(value.get("text")) for value in visual_results.values()),
            "ocr": visual_results,
            "cache_path": cache_path,
        }
        return text, details

    if item.kind == "document":
        started = time.monotonic()
        if progress:
            progress.emit(
                "document",
                "start",
                source=item.source_path,
                engine=config.ocr_engine or "docling",
            )
        try:
            result = convert_document(_source_value(item), config, progress=progress)
        except Exception:
            if progress:
                progress.emit(
                    "document",
                    "failed",
                    source=item.source_path,
                    elapsed=f"{time.monotonic() - started:.1f}s",
                )
            raise
        status, errors = _conversion_status(result)
        cache_path = _cache_docling(result.document, item, config)
        body = export_markdown(result.document)
        if progress:
            progress.emit(
                "document",
                "complete",
                result=status,
                source=item.source_path,
                route=str(getattr(result, "route", "docling")),
                elapsed=f"{time.monotonic() - started:.1f}s",
            )
        return render_document_markdown(
            title=title,
            metadata=_metadata(item, config, status, "document"),
            body=body,
        ), {
            "status": status,
            "errors": errors,
            "cache_path": cache_path,
            "content_sha256": normalized_text_hash(body),
            "conversion_route": str(getattr(result, "route", "docling")),
        }

    if item.kind == "docling" and item.absolute_path:
        if item.extension == ".vtt":
            events = _vtt_events(item.absolute_path)
            text = render_media_markdown(
                title=title,
                metadata=_metadata(item, config, "complete", "media_transcript"),
                events=events,
                visual_text={},
            )
            return text, {
                "status": "complete",
                "errors": [],
                "events": [event.manifest_dict() for event in events],
            }
        started = time.monotonic()
        if progress:
            progress.emit("document", "start", source=item.source_path, engine="docling")
        document = load_docling_document(item.absolute_path)
        events = list(iter_events(document))
        if any(event.track is not None for event in events):
            text = render_media_markdown(
                title=title,
                metadata=_metadata(item, config, "complete", "media_transcript"),
                events=events,
                visual_text={},
            )
        else:
            body = export_markdown(document)
            text = render_document_markdown(
                title=title,
                metadata=_metadata(item, config, "complete", "document"),
                body=body,
            )
        details = {
            "status": "complete",
            "errors": [],
            "events": [event.manifest_dict() for event in events],
        }
        if not any(event.track is not None for event in events):
            details["content_sha256"] = normalized_text_hash(body)
        if progress:
            progress.emit(
                "document",
                "complete",
                result="complete",
                source=item.source_path,
                route="docling-import",
                elapsed=f"{time.monotonic() - started:.1f}s",
            )
        return text, details

    raise ValueError(f"Unsupported source type: {item.kind}")


def _write_indexes(output_root: Path, records: list[dict[str, Any]]) -> None:
    rows = ["# Catalog", "", "| Kind | Source | Artifact | Status |", "| --- | --- | --- | --- |"]
    for item in records:
        artifact = item.get("output_path")
        link = f"[[{Path(str(artifact)).with_suffix('').as_posix()}]]" if artifact else ""
        kind = item.get("kind", "")
        source_path = item.get("source_path", "")
        status = item.get("status", "")
        rows.append(f"| {kind} | `{source_path}` | {link} | {status} |")
    catalog = "\n".join(rows) + "\n"
    index = (
        "# Imported Corpus\n\n"
        "1. Search [[catalog]] by title, source path, or content kind.\n"
        "2. Open the linked transcript or document.\n"
        "3. Read `### Visual Text` blocks for sampled slide or screen text.\n"
        "4. Use source provenance in frontmatter when citing content.\n"
    )
    atomic_write(output_root / "catalog.md", catalog, [output_root])
    atomic_write(output_root / "index.md", index, [output_root])
    grouped: dict[Path, list[dict[str, Any]]] = {}
    for record in records:
        output_path = record.get("output_path")
        if not output_path:
            continue
        parent = Path(str(output_path)).parent
        if parent == Path("."):
            continue
        grouped.setdefault(parent, []).append(record)
    for parent, children in grouped.items():
        directory = output_root / parent
        index_path = directory / "index.md"
        existing_index = (
            index_path.read_text(encoding="utf-8", errors="replace") if index_path.exists() else ""
        )
        is_generated_index = "generated_by: media-import-directory-index" in existing_index
        if index_path.exists() and not is_generated_index:
            index_path = directory / "directory-index.md"
        lines = [
            "---",
            "generated_by: media-import-directory-index",
            "---",
            "",
            f"# {parent.name}",
            "",
        ]
        ordered_children = sorted(
            children, key=lambda value: str(value.get("output_path", "")).casefold()
        )
        for child in ordered_children:
            child_path = Path(str(child["output_path"]))
            link = child_path.relative_to(parent).with_suffix("").as_posix()
            lines.append(f"- [[{link}]] — `{child.get('source_path', '')}`")
        atomic_write(index_path, "\n".join(lines) + "\n", [output_root])


def _run_import(
    config: Config,
    items: list[SourceItem],
    managed_kinds: set[str] | None = None,
    progress: ProgressReporter | None = None,
    conflict_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_root = config.output_root
    duplicate_groups = exact_duplicate_groups(items)
    duplicate_aliases = {
        alias: group["canonical"]
        for group in duplicate_groups
        for alias in group.get("aliases", [])
    }
    associated_vtt = {
        vtt.source_path: media.source_path
        for media in items
        if media.kind == "media"
        for vtt in [_matching_vtt(media, items)]
        if vtt is not None and config.transcription_policy != "force"
    }
    candidate_paths = {
        item.source_path: normalized_output_path(_output_source_path(item, config))
        for item in items
    }
    planned_outputs, selected_aliases, unresolved = build_output_plan(
        items,
        candidate_paths,
        conflict_decisions or {},
        {**duplicate_aliases, **associated_vtt},
    )
    if unresolved:
        names = ", ".join(unresolved)
        raise ConfigError(
            "Unresolved same-basename media conflicts; provide --conflict-decisions: "
            f"{names}"
        )
    duplicate_aliases.update(selected_aliases)

    output_root.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    source = resolve_source(config.source)
    manifest = new_manifest(
        config.public_dict(),
        {
            "path": str(source.local_path) if source.local_path else None,
            "uri": source.source_uri,
            "kind": source.kind,
        },
    )
    if manifest_path.exists():
        old_manifest = load_manifest(manifest_path)
        old_by_source = {
            str(item.get("source_path")): item for item in old_manifest.get("items", [])
        }
        same_profile = old_manifest.get("config") == config.public_dict()
    else:
        old_by_source = {}
        same_profile = False
    if managed_kinds is not None:
        manifest["items"].extend(
            dict(item)
            for item in old_by_source.values()
            if item.get("kind") not in managed_kinds and not item.get("stale")
        )
    manifest["duplicates"] = duplicate_groups
    content_canonicals = {
        str(item["content_sha256"]): str(item.get("output_path", ""))
        for item in old_by_source.values()
        if item.get("status") == "complete" and item.get("content_sha256")
    }
    if progress:
        progress.emit("import", "start", items=len(items), output=str(output_root))

    total = len(items)
    for index, item in enumerate(items, start=1):
        if progress:
            progress.emit(
                "item",
                "start",
                index=index,
                total=total,
                kind=item.kind,
                source=item.source_path,
            )
        record: dict[str, Any] = {
            "source_path": item.source_path,
            "source_uri": item.source_uri,
            "source_sha256": item.sha256,
            "size": item.size,
            "mtime_ns": item.mtime_ns,
            "kind": item.kind,
            "status": "pending",
            "warnings": [],
            "errors": [],
        }
        if item.source_path in duplicate_aliases:
            record.update(
                {
                    "status": "duplicate",
                    "canonical_source_path": duplicate_aliases[item.source_path],
                }
            )
            manifest["items"].append(record)
            save_manifest(manifest_path, manifest, output_root)
            if progress:
                progress.emit(
                    "item",
                    "complete",
                    index=index,
                    total=total,
                    result="duplicate",
                    source=item.source_path,
                )
            continue
        if item.source_path in associated_vtt:
            record.update(
                {
                    "status": "reused",
                    "canonical_source_path": associated_vtt[item.source_path],
                }
            )
            manifest["items"].append(record)
            save_manifest(manifest_path, manifest, output_root)
            if progress:
                progress.emit(
                    "item",
                    "complete",
                    index=index,
                    total=total,
                    result="reused",
                    source=item.source_path,
                )
            continue
        if item.kind == "unsupported":
            record.update(
                {"status": "unsupported", "errors": [f"Unsupported source type: {item.kind}"]}
            )
            manifest["items"].append(record)
            save_manifest(manifest_path, manifest, output_root)
            if progress:
                progress.emit(
                    "item",
                    "complete",
                    index=index,
                    total=total,
                    result="unsupported",
                    source=item.source_path,
                )
            continue
        try:
            source_hash = item.sha256 or hashlib.sha256(item.source_path.encode()).hexdigest()
            planned_relative = planned_outputs[item.source_path]
            if planned_relative == candidate_paths[item.source_path]:
                output_path = output_path_for(
                    _output_source_path(item, config), output_root, source_hash
                )
            else:
                output_path = output_path_for(planned_relative, output_root, source_hash)
            relative_output = output_path.relative_to(output_root).as_posix()
            previous = old_by_source.get(item.source_path)
            if (
                same_profile
                and previous
                and previous.get("source_sha256") == item.sha256
                and previous.get("output_path") == relative_output
                and previous.get("output_sha256")
                and output_path.exists()
                and sha256_file(output_path) == previous["output_sha256"]
            ):
                reused = dict(previous)
                reused["resumed"] = True
                manifest["items"].append(reused)
                save_manifest(manifest_path, manifest, output_root)
                if progress:
                    progress.emit(
                        "item",
                        "complete",
                        index=index,
                        total=total,
                        result="resumed",
                        source=item.source_path,
                    )
                continue
            if (
                previous
                and output_path.exists()
                and previous.get("output_sha256")
                and sha256_file(output_path) != previous["output_sha256"]
            ):
                record.update(
                    {
                        "status": "conflict",
                        "output_path": relative_output,
                        "errors": ["Existing owned output was modified; refusing to overwrite"],
                    }
                )
                manifest["items"].append(record)
                save_manifest(manifest_path, manifest, output_root)
                if progress:
                    progress.emit(
                        "item",
                        "complete",
                        index=index,
                        total=total,
                        result="conflict",
                        source=item.source_path,
                    )
                continue
            try:
                text, details = _process_item(item, items, config, output_root, progress)
            finally:
                if item.kind == "media":
                    release_media_memory()
            content_hash = details.get("content_sha256")
            if item.kind == "document" and content_hash in content_canonicals:
                record.update(details)
                record.update(
                    {
                        "status": "duplicate",
                        "canonical_output_path": content_canonicals[str(content_hash)],
                    }
                )
                manifest["items"].append(record)
                save_manifest(manifest_path, manifest, output_root)
                if progress:
                    progress.emit(
                        "item",
                        "complete",
                        index=index,
                        total=total,
                        result="duplicate",
                        source=item.source_path,
                    )
                continue
            atomic_write(output_path, text, [output_root])
            record.update(details)
            if config.asset_mode == "copy" and item.absolute_path is not None:
                original_relative = Path("originals") / Path(item.source_path.replace("!/", "/"))
                original_path = output_root / original_relative
                atomic_write(original_path, item.absolute_path.read_bytes(), [output_root])
                record["original_copy"] = original_relative.as_posix()
            elif config.asset_mode == "copy":
                record["warnings"].append(
                    "Remote source was not copied; conversion used the sanitized source URI"
                )
            record.update(
                {
                    "output_path": relative_output,
                    "output_sha256": sha256_file(output_path),
                }
            )
            if content_hash:
                content_canonicals[str(content_hash)] = relative_output
        except PdfPasswordRequired as exc:
            record.update({"status": "blocked", "errors": [str(exc)]})
        except Exception as exc:
            record.update({"status": "failed", "errors": [str(exc)]})
        manifest["items"].append(record)
        save_manifest(manifest_path, manifest, output_root)
        if progress:
            progress.emit(
                "item",
                "complete",
                index=index,
                total=total,
                result=record["status"],
                source=item.source_path,
            )

    current_sources = {item.source_path for item in items}
    if progress:
        progress.emit("stale-cleanup", "start")
    stale_removed = 0
    stale_conflicts = 0
    for source_path, previous in old_by_source.items():
        if managed_kinds is not None and previous.get("kind") not in managed_kinds:
            continue
        if source_path in current_sources or not previous.get("output_path"):
            continue
        stale_path = (output_root / str(previous["output_path"])).resolve()
        expected_hash = previous.get("output_sha256")
        stale_record = dict(previous)
        if (
            stale_path.exists()
            and expected_hash
            and sha256_file(stale_path) == expected_hash
            and 'importer: "media-import"'
            in stale_path.read_text(encoding="utf-8", errors="replace")
        ):
            stale_path.unlink()
            stale_record.update({"status": "removed", "stale": True})
            stale_removed += 1
        elif stale_path.exists():
            stale_record.update(
                {
                    "status": "conflict",
                    "stale": True,
                    "errors": ["Stale owned output was modified; refusing to remove"],
                }
            )
            stale_conflicts += 1
        else:
            stale_record.update({"status": "removed", "stale": True})
        manifest["items"].append(stale_record)
        save_manifest(manifest_path, manifest, output_root)
    if progress:
        progress.emit(
            "stale-cleanup",
            "complete",
            removed=stale_removed,
            conflicts=stale_conflicts,
        )

    if progress:
        progress.emit("indexes", "start")
    _write_indexes(output_root, manifest["items"])
    if progress:
        progress.emit("indexes", "complete")
        progress.emit("validation", "start")
    validation = validate_corpus(output_root, source.local_path)
    if progress:
        progress.emit("validation", "complete", result=validation["status"])
        progress.emit("import", "complete", result=validation["status"])
    return {
        "message": "Import completed",
        "output_dir": str(output_root),
        "manifest": str(manifest_path),
        "counts": status_counts(load_manifest(manifest_path)),
        "validation": validation,
    }


def _refresh_indexes(config: Config) -> dict[str, Any]:
    manifest_path = config.output_root / "manifest.json"
    if not manifest_path.exists():
        raise ConfigError("Cannot refresh indexes without an existing manifest")
    manifest = load_manifest(manifest_path)
    _write_indexes(config.output_root, manifest.get("items", []))
    validation = validate_corpus(config.output_root, None)
    return {
        "message": "Indexes refreshed",
        "output_dir": str(config.output_root),
        "manifest": str(manifest_path),
        "counts": status_counts(manifest),
        "validation": validation,
    }


def _parse_only(value: str) -> set[str]:
    selected = {item.strip() for item in value.split(",") if item.strip()}
    allowed = {"media", "documents", "indexes"}
    invalid = selected - allowed
    if invalid or not selected:
        names = ", ".join(sorted(invalid)) if invalid else "empty selection"
        raise ConfigError(f"Unsupported --only value: {names}")
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_corpus(
                args.output_dir.resolve(), args.source.resolve() if args.source else None
            )
            _emit(result, args.json_output)
            return 2 if result["status"] == "failed" else 1 if result["status"] == "warning" else 0
        if args.command == "status":
            manifest = load_manifest(args.output_dir.resolve() / "manifest.json")
            result = {
                "output_dir": str(args.output_dir.resolve()),
                "counts": status_counts(manifest),
                "validation": manifest.get("validation", {}),
            }
            _emit(result, args.json_output)
            return 0
        if args.command == "compare-transcripts":
            result = compare_transcripts(args.canonical, args.variant)
            _emit(result, args.json_output)
            return 0

        config = load_config(overrides=_overrides(args), config_path=args.config)
        progress = ProgressReporter(verbose=config.verbose)
        only = _parse_only(args.only) if args.command == "import" else set()
        inspection, items = _inspect(
            config,
            for_import=False,
            progress=progress,
        )
        if args.command == "inspect" or args.dry_run:
            inspection["dry_run"] = args.command == "import"
            if args.command == "import":
                inspection["only"] = sorted(only)
                decisions = _load_conflict_decisions(args.conflict_decisions)
                duplicates = exact_duplicate_groups(items)
                duplicate_aliases = {
                    alias: group["canonical"]
                    for group in duplicates
                    for alias in group.get("aliases", [])
                }
                associated_vtt = {
                    vtt.source_path: media.source_path
                    for media in items
                    if media.kind == "media"
                    for vtt in [_matching_vtt(media, items)]
                    if vtt is not None and config.transcription_policy != "force"
                }
                candidates = {
                    item.source_path: normalized_output_path(_output_source_path(item, config))
                    for item in items
                }
                _, _, unresolved = build_output_plan(
                    items,
                    candidates,
                    decisions,
                    {**duplicate_aliases, **associated_vtt},
                )
                inspection["unresolved_conflicts"] = unresolved
            _emit(inspection, args.json_output)
            return 3 if any(item["level"] == "error" for item in inspection["diagnostics"]) else 0
        if not args.confirmed:
            raise ConfigError("A real import requires --confirmed after reviewing --dry-run")
        if only == {"indexes"}:
            result = _refresh_indexes(config)
            _emit(result, args.json_output)
            return 0 if result["validation"]["status"] == "clean" else 1
        items = _expand_archives(items, config, progress)
        managed_kinds: set[str] = set()
        if "media" in only:
            managed_kinds.add("media")
        if "documents" in only:
            managed_kinds.update({"document", "docling"})
        items = [item for item in items if item.kind in managed_kinds or item.kind == "unsupported"]
        expanded_diagnostics = run_preflight(config, items, for_import=True)
        if has_errors(expanded_diagnostics):
            _emit(
                {"diagnostics": [item.public_dict() for item in expanded_diagnostics]},
                args.json_output,
            )
            return 3
        decisions = _load_conflict_decisions(args.conflict_decisions)
        result = _run_import(config, items, managed_kinds, progress, decisions)
        _emit(result, args.json_output)
        validation_status = result["validation"]["status"]
        code = 2 if validation_status == "failed" else 1 if validation_status == "warning" else 0
        if args.fail_on_warning and code == 1:
            return 2
        return code
    except (ConfigError, ValueError) as exc:
        print(f"media-import: {exc}", file=sys.stderr)
        return 3
