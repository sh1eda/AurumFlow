from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .types import Signal


@dataclass(frozen=True)
class PaperLedger:
    path: Path

    def record_signal(self, signal: Signal) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "signal", "payload": signal.to_dict()}, sort_keys=True) + "\n")

    def read_events(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def place_real_order(*_args, **_kwargs):
    raise RuntimeError("Real-money execution is not implemented or authorized.")
