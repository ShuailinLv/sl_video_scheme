from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, session_dir: str, enabled: bool = True) -> None:
        self.session_dir = Path(session_dir)
        self.enabled = bool(enabled)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self._lock = threading.Lock()

    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        ts_monotonic_sec: float | None = None,
        session_tick: int | None = None,
    ) -> None:
        if not self.enabled:
            return

        record = {
            "event_type": str(event_type),
            "ts_monotonic_sec": (
                float(ts_monotonic_sec) if ts_monotonic_sec is not None else None
            ),
            "session_tick": int(session_tick) if session_tick is not None else None,
            "payload": payload,
        }

        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")