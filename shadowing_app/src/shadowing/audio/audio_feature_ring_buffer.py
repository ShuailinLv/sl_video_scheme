from __future__ import annotations

from collections import deque

from shadowing.audio.frame_feature_extractor import AudioFrameFeature


class AudioFeatureRingBuffer:
    def __init__(self, max_duration_sec: float = 6.0) -> None:
        self.max_duration_sec = max(1.0, float(max_duration_sec))
        self._items: deque[AudioFrameFeature] = deque()

    def reset(self) -> None:
        self._items.clear()

    def append_many(self, frames: list[AudioFrameFeature]) -> None:
        for item in frames:
            self._items.append(item)
        self._trim()

    def get_recent(self, duration_sec: float) -> list[AudioFrameFeature]:
        if not self._items:
            return []
        latest = self._items[-1].observed_at_sec
        cutoff = latest - max(0.0, float(duration_sec))
        return [x for x in self._items if x.observed_at_sec >= cutoff]

    def latest_time_sec(self) -> float:
        if not self._items:
            return 0.0
        return float(self._items[-1].observed_at_sec)

    def _trim(self) -> None:
        if not self._items:
            return
        latest = self._items[-1].observed_at_sec
        cutoff = latest - self.max_duration_sec
        while self._items and self._items[0].observed_at_sec < cutoff:
            self._items.popleft()
