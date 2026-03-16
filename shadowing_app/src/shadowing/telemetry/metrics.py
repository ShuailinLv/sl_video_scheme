from __future__ import annotations

from dataclasses import dataclass

from shadowing.session.session_metrics import SessionMetrics


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
    """
    兼容层。
    新代码应直接使用 SessionMetrics。
    """

    def __init__(self, lesson_id: str = "") -> None:
        self._delegate = SessionMetrics(lesson_id=lesson_id)

    def mark_session_started(self, now_sec: float) -> None:
        self._delegate.mark_session_started(now_sec)

    def mark_session_ended(self, now_sec: float) -> None:
        self._delegate.mark_session_ended(now_sec)

    def observe_signal_active(self, now_sec: float) -> None:
        self._delegate.observe_signal_active(now_sec)

    def observe_asr_partial(self, now_sec: float) -> None:
        self._delegate.observe_asr_partial(now_sec)

    def observe_progress(self, now_sec: float, tracking_quality: float, is_reliable: bool) -> None:
        if self._delegate.session_started_at_sec > 0.0:
            since_start = max(0.0, float(now_sec) - self._delegate.session_started_at_sec)
        else:
            since_start = 0.0
        self._delegate.observe_progress(
            now_since_session_start_sec=since_start,
            recently_progressed=False,
            joint_confidence=float(tracking_quality),
            position_source="unknown",
            tracking_quality=float(tracking_quality),
            is_reliable=bool(is_reliable),
        )

    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        self._delegate.observe_action(action, reason, now_sec)

    def observe_tracking_mode(self, mode: str) -> None:
        self._delegate.observe_tracking_mode(mode)

    def summary(self) -> SessionMetricsSummary:
        d = self._delegate.summary_dict()
        return SessionMetricsSummary(
            first_signal_active_time_sec=d.get("first_signal_active_time_sec"),
            first_asr_partial_time_sec=d.get("first_asr_partial_time_sec"),
            first_reliable_progress_time_sec=d.get("first_reliable_progress_time_sec"),
            startup_false_hold_count=int(d.get("startup_false_hold_count", 0)),
            hold_count=int(d.get("hold_count", 0)),
            resume_count=int(d.get("resume_count", 0)),
            soft_duck_count=int(d.get("soft_duck_count", 0)),
            seek_count=int(d.get("seek_count", 0)),
            lost_count=int(d.get("lost_count", 0)),
            reacquire_count=int(d.get("reacquire_count", 0)),
            max_tracking_quality=float(d.get("max_tracking_quality", 0.0)),
            mean_tracking_quality=float(d.get("mean_tracking_quality", 0.0)),
            total_progress_updates=int(d.get("total_progress_updates", 0)),
        )

    def summary_dict(self) -> dict:
        return self._delegate.summary_dict()

    @property
    def session_metrics(self) -> SessionMetrics:
        return self._delegate