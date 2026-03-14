from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class ReplayEvent:
    event_type: str
    payload: dict


class ReplayLoader:
    def __init__(self, events_file: str) -> None:
        self.events_file = Path(events_file)

    def __iter__(self) -> Iterator[ReplayEvent]:
        with self.events_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                yield ReplayEvent(
                    event_type=str(data.get("event_type", "")),
                    payload=dict(data.get("payload", {})),
                )