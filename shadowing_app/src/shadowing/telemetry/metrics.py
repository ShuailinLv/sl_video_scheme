from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SessionMetricsSummary:
    first_signal_active_time_sec: float | None
    first_asr_partial_time_sec: float | None
    first_reliable_progress_time_sec: float | None
    startup_false_hold_count: int
    hold_count: int
    resume_count: int
    soft_duck_count: int
    seek_count: int
    lost_count: int
    reacquire_count: int
    max_tracking_quality: float
    mean_tracking_quality: float
    total_progress_updates: int


class MetricsAggregator:
    def __init__(self) -> None:
        self.session_started_at_sec = 0.0

        self.first_signal_active_time_sec: float | None = None
        self.first_asr_partial_time_sec: float | None = None
        self.first_reliable_progress_time_sec: float | None = None

        self.startup_false_hold_count = 0
        self.hold_count = 0
        self.resume_count = 0
        self.soft_duck_count = 0
        self.seek_count = 0
        self.lost_count = 0
        self.reacquire_count = 0

        self.max_tracking_quality = 0.0
        self._tracking_quality_sum = 0.0
        self.total_progress_updates = 0

    def mark_session_started(self, now_sec: float) -> None:
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = float(now_sec)

    def observe_signal_active(self, now_sec: float) -> None:
        if self.first_signal_active_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_signal_active_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_asr_partial(self, now_sec: float) -> None:
        if self.first_asr_partial_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_asr_partial_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_progress(self, now_sec: float, tracking_quality: float, is_reliable: bool) -> None:
        self.total_progress_updates += 1
        self.max_tracking_quality = max(self.max_tracking_quality, float(tracking_quality))
        self._tracking_quality_sum += float(tracking_quality)

        if is_reliable and self.first_reliable_progress_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_reliable_progress_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        if action == "hold":
            self.hold_count += 1
            if self.session_started_at_sec > 0.0 and (now_sec - self.session_started_at_sec) <= 5.0:
                if reason in ("no_progress_timeout", "reference_too_far_ahead"):
                    self.startup_false_hold_count += 1
        elif action == "resume":
            self.resume_count += 1
        elif action == "soft_duck":
            self.soft_duck_count += 1
        elif action == "seek":
            self.seek_count += 1

    def observe_tracking_mode(self, mode: str) -> None:
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1

    def summary(self) -> SessionMetricsSummary:
        mean_tracking_quality = (
            self._tracking_quality_sum / self.total_progress_updates
            if self.total_progress_updates > 0
            else 0.0
        )
        return SessionMetricsSummary(
            first_signal_active_time_sec=self.first_signal_active_time_sec,
            first_asr_partial_time_sec=self.first_asr_partial_time_sec,
            first_reliable_progress_time_sec=self.first_reliable_progress_time_sec,
            startup_false_hold_count=self.startup_false_hold_count,
            hold_count=self.hold_count,
            resume_count=self.resume_count,
            soft_duck_count=self.soft_duck_count,
            seek_count=self.seek_count,
            lost_count=self.lost_count,
            reacquire_count=self.reacquire_count,
            max_tracking_quality=self.max_tracking_quality,
            mean_tracking_quality=float(mean_tracking_quality),
            total_progress_updates=self.total_progress_updates,
        )

    def summary_dict(self) -> dict:
        s = self.summary()
        return {
            "first_signal_active_time_sec": s.first_signal_active_time_sec,
            "first_asr_partial_time_sec": s.first_asr_partial_time_sec,
            "first_reliable_progress_time_sec": s.first_reliable_progress_time_sec,
            "startup_false_hold_count": s.startup_false_hold_count,
            "hold_count": s.hold_count,
            "resume_count": s.resume_count,
            "soft_duck_count": s.soft_duck_count,
            "seek_count": s.seek_count,
            "lost_count": s.lost_count,
            "reacquire_count": s.reacquire_count,
            "max_tracking_quality": s.max_tracking_quality,
            "mean_tracking_quality": s.mean_tracking_quality,
            "total_progress_updates": s.total_progress_updates,
        }