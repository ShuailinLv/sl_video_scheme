from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int = 1
    device: int | str | None = None
    latency: str | float = "high"
    blocksize: int = 0
    bluetooth_output_offset_sec: float = 0.0