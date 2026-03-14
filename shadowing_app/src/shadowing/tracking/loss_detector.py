from __future__ import annotations

from collections import deque
from statistics import pstdev

from shadowing.types import TrackingMode, TrackingSnapshot


class LossDetector:
    def __init__(
        self,
        jitter_window: int = 6,
        weak_quality_threshold: float = 0.56,
        lost_quality_threshold: float = 0.40,
        max_jitter_sigma: float = 8.0,
        lost_run_threshold: int = 4,
    ) -> None:
        self.jitter_window = int(jitter_window)
        self.weak_quality_threshold = float(weak_quality_threshold)
        self.lost_quality_threshold = float(lost_quality_threshold)
        self.max_jitter_sigma = float(max_jitter_sigma)
        self.lost_run_threshold = int(lost_run_threshold)

        self._recent_candidates: deque[int] = deque(maxlen=self.jitter_window)
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0

    def reset(self) -> None:
        self._recent_candidates.clear()
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0

    def update(
        self,
        snapshot: TrackingSnapshot,
        overall_score: float,
        is_reliable: bool,
    ) -> tuple[TrackingMode, float]:
        candidate_idx = int(snapshot.candidate_ref_idx)

        series = list(self._recent_candidates) + [candidate_idx]
        if len(series) <= 1:
            temporal_consistency = 0.72
        else:
            sigma = pstdev(series)
            temporal_consistency = max(0.0, 1.0 - min(1.0, sigma / self.max_jitter_sigma))

        if is_reliable:
            self._last_reliable_at_sec = float(snapshot.emitted_at_sec)
            self._good_quality_run += 1
            self._low_quality_run = 0
        else:
            self._low_quality_run += 1
            self._good_quality_run = 0

        if is_reliable and overall_score >= 0.78 and self._good_quality_run >= 1:
            mode = TrackingMode.LOCKED
        elif overall_score >= self.weak_quality_threshold and temporal_consistency >= 0.28:
            mode = TrackingMode.WEAK_LOCKED
        elif (
            self._last_reliable_at_sec > 0.0
            and (snapshot.emitted_at_sec - self._last_reliable_at_sec) <= 2.0
        ):
            mode = TrackingMode.REACQUIRING
        elif overall_score < self.lost_quality_threshold and self._low_quality_run >= self.lost_run_threshold:
            mode = TrackingMode.LOST
        else:
            mode = TrackingMode.REACQUIRING

        self._recent_candidates.append(candidate_idx)
        return mode, float(temporal_consistency)