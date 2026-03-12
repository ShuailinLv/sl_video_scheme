from __future__ import annotations

import time
from dataclasses import dataclass

from shadowing.interfaces.controller import Controller
from shadowing.types import AlignResult, ControlAction, ControlDecision, PlaybackStatus
from shadowing.realtime.control.state_estimator import ControlStateEstimator


@dataclass(slots=True)
class AdaptiveControlPolicy:
    min_confidence: float = 0.60

    hold_ema_threshold: float = 0.45
    resume_ema_threshold: float = 0.18
    seek_if_lag_sec: float = -0.90

    lead_slope_threshold: float = 0.03
    worsening_frames_needed: int = 2

    seek_cooldown_sec: float = 0.40
    resume_min_lead_sec: float = -0.35

    # 运行开关
    ducking_only: bool = False
    disable_seek: bool = False
    disable_hold: bool = False


class AdaptiveStateMachineController(Controller):
    """
    自适应控制器：
    - 动态 target lead
    - 趋势型 HOLD
    - ducking 输出
    - resume 收紧
    - 调试开关：ducking-only / disable-seek / disable-hold
    """

    def __init__(
        self,
        estimator: ControlStateEstimator,
        policy: AdaptiveControlPolicy | None = None,
        total_duration_sec: float | None = None,
    ) -> None:
        self.estimator = estimator
        self.policy = policy or AdaptiveControlPolicy()
        self.total_duration_sec = total_duration_sec

        self._last_seek_at = 0.0
        self._worsening_count = 0

    def note_asr_event(self, event) -> None:
        self.estimator.note_asr_event(event)

    def note_hold(self) -> None:
        self.estimator.note_hold()

    def decide(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlDecision:
        features = self.estimator.update(playback, alignment)

        if alignment is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_alignment",
                target_gain=features.suggested_gain,
            )

        if features.alignment_conf < self.policy.min_confidence:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="low_confidence",
                lead_sec=features.lead_raw,
                target_gain=features.suggested_gain,
            )

        lead_raw = features.lead_raw
        lead_ema = features.lead_ema if features.lead_ema is not None else lead_raw
        lead_slope = features.lead_slope if features.lead_slope is not None else 0.0
        dynamic_target = features.dynamic_target_lead

        # ducking-only：只输出 gain，不接管播放状态
        if self.policy.ducking_only:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="ducking_only",
                lead_sec=lead_raw,
                target_gain=features.suggested_gain,
            )

        # 趋势型 HOLD
        if (
            lead_ema is not None
            and lead_ema > self.policy.hold_ema_threshold
            and lead_slope > self.policy.lead_slope_threshold
        ):
            self._worsening_count += 1
        else:
            self._worsening_count = 0

        if (
            not self.policy.disable_hold
            and self._worsening_count >= self.policy.worsening_frames_needed
        ):
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="lead_worsening_hold",
                lead_sec=lead_raw,
                target_gain=features.suggested_gain,
            )

        if (
            lead_ema is not None
            and lead_ema <= self.policy.resume_ema_threshold
            and lead_ema >= self.policy.resume_min_lead_sec
        ):
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="user_caught_up",
                lead_sec=lead_raw,
                target_gain=features.suggested_gain,
            )

        now = time.monotonic()
        if (
            not self.policy.disable_seek
            and features.alignment_stable
            and lead_ema is not None
            and lead_ema < self.policy.seek_if_lag_sec
            and (now - self._last_seek_at) >= self.policy.seek_cooldown_sec
        ):
            target_time = alignment.ref_time_sec + dynamic_target
            if self.total_duration_sec is not None:
                target_time = min(max(0.0, target_time), self.total_duration_sec)
            else:
                target_time = max(0.0, target_time)

            self._last_seek_at = now
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=target_time,
                lead_sec=lead_raw,
                target_gain=features.suggested_gain,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead_raw,
            target_gain=features.suggested_gain,
        )