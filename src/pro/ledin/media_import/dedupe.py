from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from .config import EBOOK_FORMAT_PREFERENCE
from .inventory import SourceItem

EBOOK_EXTENSIONS = {".epub", ".fb2", ".fb2.zip", ".fbz", ".mobi", ".azw", ".azw3"}


def exact_duplicate_groups(
    items: Iterable[SourceItem],
    ebook_format_preference: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = defaultdict(list)
    items_by_source: dict[str, SourceItem] = {}
    for item in items:
        if item.sha256:
            groups[item.sha256].append(item.source_path)
            items_by_source[item.source_path] = item

    selected_preference = tuple(
        value.casefold().lstrip(".")
        for value in (ebook_format_preference or EBOOK_FORMAT_PREFERENCE)
    )
    preference = selected_preference + tuple(
        format_name
        for format_name in EBOOK_FORMAT_PREFERENCE
        if format_name not in selected_preference
    )
    ebook_ranks = {
        extension: index for index, extension in enumerate(preference)
    }

    def canonical_path(paths: list[str]) -> str:
        ebook_paths = [
            path
            for path in paths
            if items_by_source[path].extension.casefold() in EBOOK_EXTENSIONS
        ]
        if len(ebook_paths) != len(paths):
            return paths[0]
        return min(
            ebook_paths,
            key=lambda path: (
                ebook_ranks.get(
                    items_by_source[path].extension.casefold().lstrip("."),
                    len(preference),
                ),
                path.casefold(),
            ),
        )

    result: list[dict[str, object]] = []
    for digest, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        canonical = canonical_path(paths)
        result.append(
            {
                "sha256": digest,
                "canonical": canonical,
                "aliases": [path for path in paths if path != canonical],
            }
        )
    return result


def normalized_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
