from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Track:
    start_time: float | None
    end_time: float | None
    voice: str | None


@dataclass(frozen=True)
class DocumentEvent:
    event_id: str
    kind: str
    text: str
    track: Track | None
    item: Any

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "text": self.text,
            "track": asdict(self.track) if self.track else None,
        }


def _identifier(item: Any, index: int) -> str:
    for name in ("self_ref", "id", "cref"):
        value = getattr(item, name, None)
        if value:
            return str(value)
    return f"item-{index}"


def _track(item: Any) -> Track | None:
    sources = getattr(item, "source", None) or []
    if not sources:
        return None
    source = sources[0]
    start = getattr(source, "start_time", None)
    end = getattr(source, "end_time", None)
    return Track(
        float(start) if start is not None else None,
        float(end) if end is not None else None,
        str(getattr(source, "voice", "") or "") or None,
    )


def _kind(item: Any) -> str:
    class_name = type(item).__name__.casefold()
    label = str(getattr(item, "label", "")).casefold()
    if "picture" in class_name or "picture" in label:
        return "picture"
    if hasattr(item, "text"):
        return "text"
    return "other"


def iter_events(document: Any) -> Iterator[DocumentEvent]:
    for index, pair in enumerate(document.iterate_items()):
        item = pair[0] if isinstance(pair, tuple) else pair
        kind = _kind(item)
        text = str(getattr(item, "text", "") or "").strip()
        if kind == "other" or (kind == "text" and not text):
            continue
        yield DocumentEvent(_identifier(item, index), kind, text, _track(item), item)
