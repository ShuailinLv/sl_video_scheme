from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _f(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _b(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class ControlDecision:
    action: str
    reason: str
    target_gain: float
    seek_to_ref_time_sec: float | None = None


class PlaybackController:
    """
    旧 controller 的过渡清理版。

    目标：
    - 输入只依赖 progress + playback/user ref time + latency calibration snapshot
    - 输出只有 action / gain / seek
    - 具体播放器怎么执行，交给上层 orchestrator
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

        self.target_lead_sec = _f(config.get("target_lead_sec"), 0.18)
        self.hold_if_lead_sec = _f(config.get("hold_if_lead_sec"), 1.05)
        self.resume_if_lead_sec = _f(config.get("resume_if_lead_sec"), 0.36)
        self.seek_if_lag_sec = _f(config.get("seek_if_lag_sec"), -2.60)
        self.min_confidence = _f(config.get("min_confidence"), 0.70)
        self.seek_cooldown_sec = _f(config.get("seek_cooldown_sec"), 2.20)
        self.gain_following = _f(config.get("gain_following"), 0.52)
        self.gain_transition = _f(config.get("gain_transition"), 0.72)
        self.gain_soft_duck = _f(config.get("gain_soft_duck"), 0.36)
        self.startup_grace_sec = _f(config.get("startup_grace_sec"), 3.2)
        self.low_confidence_hold_sec = _f(config.get("low_confidence_hold_sec"), 2.2)
        self.guide_play_sec = _f(config.get("guide_play_sec"), 3.20)
        self.no_progress_hold_min_play_sec = _f(config.get("no_progress_hold_min_play_sec"), 5.80)
        self.progress_stale_sec = _f(config.get("progress_stale_sec"), 1.45)
        self.hold_trend_sec = _f(config.get("hold_trend_sec"), 1.00)
        self.tracking_quality_hold_min = _f(config.get("tracking_quality_hold_min"), 0.60)
        self.tracking_quality_seek_min = _f(config.get("tracking_quality_seek_min"), 0.84)
        self.resume_from_hold_speaking_lead_slack_sec = _f(
            config.get("resume_from_hold_speaking_lead_slack_sec"),
            0.72,
        )
        self.disable_seek = _b(config.get("disable_seek"), False)

        self._started_at_sec = 0.0
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False

    def reset(self, *, started_at_sec: float) -> None:
        self._started_at_sec = float(started_at_sec)
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False

    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> ControlDecision:
        if progress_estimate is None:
            return ControlDecision(
                action="guide",
                reason="no_progress_estimate",
                target_gain=self.gain_transition,
            )

        est_ref_time_sec = _f(getattr(progress_estimate, "estimated_ref_time_sec", 0.0), 0.0)
        progress_age_sec = _f(getattr(progress_estimate, "progress_age_sec", 9999.0), 9999.0)
        joint_confidence = _f(getattr(progress_estimate, "joint_confidence", 0.0), 0.0)
        tracking_quality = _f(getattr(progress_estimate, "tracking_quality", 0.0), 0.0)
        active_speaking = bool(getattr(progress_estimate, "active_speaking", False))
        recently_progressed = bool(getattr(progress_estimate, "recently_progressed", False))
        user_state = str(getattr(progress_estimate, "user_state", "UNKNOWN"))
        position_source = str(getattr(progress_estimate, "position_source", "text"))

        target_lead_sec = self.target_lead_sec
        if latency_state is not None:
            target_lead_sec = _f(
                getattr(latency_state, "baseline_target_lead_sec", self.target_lead_sec),
                self.target_lead_sec,
            )

        lead_sec = _f(playback_ref_time_sec, 0.0) - est_ref_time_sec - target_lead_sec
        session_age_sec = max(0.0, float(now_sec) - self._started_at_sec)

        if session_age_sec <= self.startup_grace_sec:
            return ControlDecision(
                action="guide",
                reason="startup_grace",
                target_gain=self.gain_transition,
            )

        if joint_confidence < self.min_confidence:
            if progress_age_sec >= self.low_confidence_hold_sec:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="low_confidence",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="confidence_recovering",
                target_gain=self.gain_soft_duck,
            )

        if progress_age_sec >= self.progress_stale_sec:
            if active_speaking:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="speaking_but_no_progress",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="no_recent_progress",
                target_gain=self.gain_soft_duck,
            )

        if tracking_quality < self.tracking_quality_hold_min and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="weak_tracking_while_speaking",
                target_gain=0.0,
            )

        if lead_sec >= self.hold_if_lead_sec and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="lead_too_large",
                target_gain=0.0,
            )

        if (
            not self.disable_seek
            and lead_sec <= self.seek_if_lag_sec
            and tracking_quality >= self.tracking_quality_seek_min
            and joint_confidence >= self.min_confidence
            and (now_sec - self._last_seek_at_sec) >= self.seek_cooldown_sec
        ):
            self._last_seek_at_sec = float(now_sec)
            self._leave_hold()
            return ControlDecision(
                action="seek",
                reason="lag_too_large",
                target_gain=self.gain_transition,
                seek_to_ref_time_sec=max(0.0, est_ref_time_sec + target_lead_sec),
            )

        if self._is_holding:
            if (
                lead_sec <= self.resume_if_lead_sec + (self.resume_from_hold_speaking_lead_slack_sec if active_speaking else 0.0)
                and recently_progressed
                and tracking_quality >= self.tracking_quality_hold_min
            ):
                self._leave_hold()
                return ControlDecision(
                    action="resume",
                    reason="hold_released",
                    target_gain=self.gain_transition,
                )
            return ControlDecision(
                action="hold",
                reason="holding",
                target_gain=0.0,
            )

        if user_state in {"REJOINING", "HESITATING"}:
            return ControlDecision(
                action="duck",
                reason=f"user_state_{user_state.lower()}",
                target_gain=self.gain_soft_duck,
            )

        if user_state in {"FOLLOWING", "SKIPPING"} or position_source in {"joint", "audio"}:
            return ControlDecision(
                action="follow",
                reason="tracking_ok",
                target_gain=self.gain_following,
            )

        return ControlDecision(
            action="guide",
            reason="fallback",
            target_gain=self.gain_transition,
        )

    def _enter_hold(self, now_sec: float) -> None:
        if not self._is_holding:
            self._is_holding = True
            self._hold_started_at_sec = float(now_sec)

    def _leave_hold(self) -> None:
        self._is_holding = False
        self._hold_started_at_sec = 0.0