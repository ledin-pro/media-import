from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from .inventory import SourceItem


def exact_duplicate_groups(items: Iterable[SourceItem]) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.sha256:
            groups[item.sha256].append(item.source_path)
    return [
        {"sha256": digest, "canonical": paths[0], "aliases": paths[1:]}
        for digest, paths in sorted(groups.items())
        if len(paths) > 1
    ]


def normalized_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
