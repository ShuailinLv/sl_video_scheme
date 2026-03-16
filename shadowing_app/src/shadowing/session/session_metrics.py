from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


_STARTUP_FALSE_HOLD_REASONS = {
    "no_progress_timeout",
    "reference_too_far_ahead",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if out != out:
        return float(default)
    return float(out)


@dataclass(slots=True)
class SessionMetrics:
    """
    单轨 session metrics 主实现。

    兼容目标：
    1. 保留旧 metrics.summary_dict() 里的关键字段，避免 profile_store / auto_tuner / evaluator 立刻失配
    2. 允许 orchestrator 直接记录更丰富的 progress / tracking / control 统计
    """

    lesson_id: str = ""

    session_started_at_sec: float = 0.0
    session_ended_at_sec: float = 0.0

    first_signal_active_time_sec: float | None = None
    first_asr_partial_time_sec: float | None = None
    first_reliable_progress_time_sec: float | None = None

    startup_false_hold_count: int = 0
    hold_count: int = 0
    resume_count: int = 0
    soft_duck_count: int = 0
    seek_count: int = 0
    lost_count: int = 0
    reacquire_count: int = 0

    max_tracking_quality: float = 0.0
    _tracking_quality_sum: float = 0.0
    total_progress_updates: int = 0

    tracking_total: int = 0
    tracking_stable_count: int = 0
    tracking_mode_counter: Counter[str] = field(default_factory=Counter)

    progress_recent_count: int = 0
    position_source_counter: Counter[str] = field(default_factory=Counter)
    joint_confidence_sum: float = 0.0

    signal_active_events: int = 0
    asr_partial_count: int = 0

    action_reason_counter: Counter[str] = field(default_factory=Counter)

    def mark_session_started(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        if self.session_ended_at_sec < self.session_started_at_sec:
            self.session_ended_at_sec = self.session_started_at_sec

    def mark_session_ended(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        self.session_ended_at_sec = max(now_sec, self.session_started_at_sec)

    def observe_signal_active(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.signal_active_events += 1
        if self.first_signal_active_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_signal_active_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_asr_partial(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.asr_partial_count += 1
        if self.first_asr_partial_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_asr_partial_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_progress(
        self,
        *,
        now_since_session_start_sec: float,
        recently_progressed: bool,
        joint_confidence: float,
        position_source: str,
        tracking_quality: float | None = None,
        is_reliable: bool | None = None,
    ) -> None:
        self.total_progress_updates += 1

        tq = _safe_float(tracking_quality, 0.0) if tracking_quality is not None else 0.0
        jc = max(0.0, min(1.0, _safe_float(joint_confidence, 0.0)))
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq
        self._tracking_quality_sum += tq
        self.joint_confidence_sum += jc

        if recently_progressed:
            self.progress_recent_count += 1

        source = str(position_source or "unknown")
        self.position_source_counter[source] += 1

        if is_reliable and self.first_reliable_progress_time_sec is None:
            self.first_reliable_progress_time_sec = max(0.0, _safe_float(now_since_session_start_sec))

    def observe_tracking(
        self,
        *,
        tracking_mode: str,
        tracking_quality: float,
        stable: bool,
    ) -> None:
        self.tracking_total += 1
        mode = str(tracking_mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if stable:
            self.tracking_stable_count += 1

        tq = _safe_float(tracking_quality, 0.0)
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq

        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1

    def observe_tracking_mode(self, mode: str) -> None:
        """
        兼容旧接口。仅在还没切完的地方保留。
        """
        mode = str(mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1

    def observe_control(
        self,
        *,
        action: str,
        now_since_session_start_sec: float,
        startup_grace_sec: float,
        reason: str | None = None,
    ) -> None:
        action = str(action or "unknown")
        reason = str(reason or "").strip()

        if action == "hold":
            self.hold_count += 1
            if now_since_session_start_sec <= max(0.0, _safe_float(startup_grace_sec)):
                if reason in _STARTUP_FALSE_HOLD_REASONS:
                    self.startup_false_hold_count += 1
        elif action == "resume":
            self.resume_count += 1
        elif action == "soft_duck":
            self.soft_duck_count += 1
        elif action == "seek":
            self.seek_count += 1

        if reason:
            self.action_reason_counter[f"{action}:{reason}"] += 1

    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        """
        兼容旧 telemetry.metrics.MetricsAggregator.observe_action(...) 入口。
        """
        if self.session_started_at_sec > 0.0:
            since_start = max(0.0, _safe_float(now_sec) - self.session_started_at_sec)
        else:
            since_start = 0.0
        self.observe_control(
            action=action,
            now_since_session_start_sec=since_start,
            startup_grace_sec=5.0,
            reason=reason,
        )

    def mean_tracking_quality(self) -> float:
        if self.total_progress_updates <= 0:
            return 0.0
        return float(self._tracking_quality_sum / self.total_progress_updates)

    def summary_dict(self) -> dict[str, Any]:
        """
        兼容旧版关键字段 + 新版 richer 字段。
        """
        duration_sec = 0.0
        if self.session_started_at_sec > 0.0 and self.session_ended_at_sec >= self.session_started_at_sec:
            duration_sec = float(self.session_ended_at_sec - self.session_started_at_sec)

        mean_tracking_quality = self.mean_tracking_quality()

        return {
            # ---- 旧版关键字段（必须保留）----
            "first_signal_active_time_sec": self.first_signal_active_time_sec,
            "first_asr_partial_time_sec": self.first_asr_partial_time_sec,
            "first_reliable_progress_time_sec": self.first_reliable_progress_time_sec,
            "startup_false_hold_count": self.startup_false_hold_count,
            "hold_count": self.hold_count,
            "resume_count": self.resume_count,
            "soft_duck_count": self.soft_duck_count,
            "seek_count": self.seek_count,
            "lost_count": self.lost_count,
            "reacquire_count": self.reacquire_count,
            "max_tracking_quality": self.max_tracking_quality,
            "mean_tracking_quality": mean_tracking_quality,
            "total_progress_updates": self.total_progress_updates,
            # ---- 新增 richer 字段 ----
            "lesson_id": self.lesson_id,
            "session_started_at_sec": self.session_started_at_sec,
            "session_ended_at_sec": self.session_ended_at_sec,
            "session_duration_sec": duration_sec,
            "signal_active_events": self.signal_active_events,
            "asr_partial_count": self.asr_partial_count,
            "tracking_total": self.tracking_total,
            "tracking_stable_count": self.tracking_stable_count,
            "progress_recent_count": self.progress_recent_count,
            "avg_joint_confidence": (
                float(self.joint_confidence_sum / self.total_progress_updates)
                if self.total_progress_updates > 0
                else 0.0
            ),
            "tracking_mode_counter": dict(self.tracking_mode_counter),
            "position_source_counter": dict(self.position_source_counter),
            "action_reason_counter": dict(self.action_reason_counter),
        }