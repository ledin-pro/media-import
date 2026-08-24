from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any


def _tokens(path: Path) -> Counter[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    return Counter(re.findall(r"[\wёЁ]+", text.casefold()))


def compare_transcripts(canonical: Path, variant: Path) -> dict[str, Any]:
    left = _tokens(canonical)
    right = _tokens(variant)
    shared = sum((left & right).values())
    left_words = sum(left.values())
    right_words = sum(right.values())
    if min(left_words, right_words) < 20:
        label = "insufficient-evidence"
    else:
        left_coverage = shared / left_words
        right_coverage = shared / right_words
        if left_coverage >= 0.95 and right_coverage >= 0.95:
            label = "full-equivalent"
        elif min(left_coverage, right_coverage) >= 0.75 and max(
            left_coverage, right_coverage
        ) >= 0.90:
            label = "partial-variant"
        else:
            label = "different"
    return {
        "canonical_words": left_words,
        "variant_words": right_words,
        "shared_words": shared,
        "canonical_coverage": round(shared / left_words, 3) if left_words else 0.0,
        "variant_coverage": round(shared / right_words, 3) if right_words else 0.0,
        "label": label,
    }
