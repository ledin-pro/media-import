from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .docling_adapter import DocumentEvent

VISIBLE_TIMESTAMP = re.compile(r"\[time:\s*[^\]]+\]\s*", re.IGNORECASE)


def _yaml_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {_yaml_string(item)}" for item in value)
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml_string(value)}")
    lines.append("---")
    return "\n".join(lines)


def render_media_markdown(
    *,
    title: str,
    metadata: dict[str, Any],
    events: Iterable[DocumentEvent],
    visual_text: dict[str, dict[str, Any]],
) -> str:
    blocks = [frontmatter(metadata), "", f"# {title}", "", "## Content", ""]
    pending_text: list[str] = []
    previous_visual = ""

    def flush_text() -> None:
        if pending_text:
            blocks.append(" ".join(pending_text).strip())
            blocks.append("")
            pending_text.clear()

    for event in events:
        if event.kind == "text":
            cleaned = VISIBLE_TIMESTAMP.sub("", event.text).strip()
            if cleaned:
                pending_text.append(cleaned)
            continue
        flush_text()
        visual = visual_text.get(event.event_id, {})
        image_path = str(visual.get("image_path", "")).strip()
        if image_path:
            blocks.extend([f"![[{image_path}]]", ""])
        recognized = str(visual.get("text", "")).strip()
        if recognized and recognized != previous_visual:
            blocks.extend(["### Visual Text", "", recognized, ""])
            previous_visual = recognized
    flush_text()
    return "\n".join(blocks).rstrip() + "\n"


def render_document_markdown(*, title: str, metadata: dict[str, Any], body: str) -> str:
    cleaned = body.strip()
    if cleaned.startswith(f"# {title}"):
        content = cleaned
    else:
        content = f"# {title}\n\n{cleaned}" if cleaned else f"# {title}"
    return f"{frontmatter(metadata)}\n\n{content.rstrip()}\n"


def title_from_path(path: str) -> str:
    return Path(path).stem.replace("_", " ").replace("-", " ").strip() or "Source"
