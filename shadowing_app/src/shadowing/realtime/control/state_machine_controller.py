from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.types import AlignResult, ControlAction, ControlDecision, PlaybackStatus
from shadowing.realtime.control.policy import ControlPolicy


class StateMachineController(Controller):
    def __init__(
        self,
        policy: ControlPolicy | None = None,
        total_duration_sec: float | None = None,
    ) -> None:
        self.policy = policy or ControlPolicy()
        self.total_duration_sec = total_duration_sec
        self._last_seek_at = 0.0

    def decide(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlDecision:
        if alignment is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_alignment",
            )

        if alignment.confidence < self.policy.min_confidence:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="low_confidence",
            )

        lead = playback.t_ref_heard_sec - alignment.ref_time_sec

        if lead > self.policy.hold_if_lead_sec:
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="reference_too_far_ahead",
                lead_sec=lead,
            )

        if lead <= self.policy.resume_if_lead_sec:
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="user_caught_up",
                lead_sec=lead,
            )

        now = time.monotonic()
        if (
            alignment.stable
            and lead < self.policy.seek_if_lag_sec
            and (now - self._last_seek_at) >= self.policy.seek_cooldown_sec
        ):
            target_time = alignment.ref_time_sec + self.policy.target_lead_sec
            if self.total_duration_sec is not None:
                target_time = min(max(0.0, target_time), self.total_duration_sec)
            else:
                target_time = max(0.0, target_time)

            self._last_seek_at = now
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=target_time,
                lead_sec=lead,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead,
        )