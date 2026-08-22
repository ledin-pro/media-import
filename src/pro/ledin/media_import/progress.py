from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, TextIO


def _value(value: Any) -> str:
    text = str(value)
    if text and all(char.isalnum() or char in "._:/-" for char in text):
        return text
    return json.dumps(text, ensure_ascii=False)


@dataclass
class ProgressReporter:
    enabled: bool = True
    verbose: bool = False
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    interval_seconds: float = 5.0
    _last_emit: dict[str, float] = field(default_factory=dict)

    def emit(self, phase: str, status: str, *, detail: bool = False, **fields: Any) -> None:
        if not self.enabled or (detail and not self.verbose):
            return
        values = [f"phase={phase}", f"status={status}"]
        values.extend(f"{key}={_value(value)}" for key, value in fields.items())
        print(f"media-import: progress {' '.join(values)}", file=self.stream, flush=True)

    def periodic(self, key: str, phase: str, status: str, **fields: Any) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        last = self._last_emit.get(key, 0.0)
        if self.verbose or now - last >= self.interval_seconds:
            self._last_emit[key] = now
            self.emit(phase, status, **fields)
