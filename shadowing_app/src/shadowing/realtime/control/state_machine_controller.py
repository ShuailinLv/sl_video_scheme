from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.types import (
    ControlAction,
    ControlDecision,
    PlaybackState,
    PlaybackStatus,
    ProgressEstimate,
    SignalQuality,
    TrackingMode,
)


class StateMachineController(Controller):
    def __init__(self, policy: ControlPolicy, disable_seek: bool = False) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek or policy.disable_seek)
        self._session_started_at_sec = 0.0
        self._last_seek_at_sec = 0.0

        self._hold_candidate_since_sec = 0.0
        self._resume_candidate_since_sec = 0.0
        self._seek_candidate_since_sec = 0.0

        self._hold_hysteresis_sec = 0.18
        self._resume_hysteresis_sec = 0.22
        self._seek_hysteresis_sec = 0.28

    def reset(self) -> None:
        self._session_started_at_sec = 0.0
        self._last_seek_at_sec = 0.0
        self._hold_candidate_since_sec = 0.0
        self._resume_candidate_since_sec = 0.0
        self._seek_candidate_since_sec = 0.0

    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision:
        now_sec = time.monotonic()
        if self._session_started_at_sec <= 0.0:
            self._session_started_at_sec = now_sec

        speaking = self._is_speaking(signal_quality)
        session_age = max(0.0, now_sec - self._session_started_at_sec)

        if progress is None:
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            if speaking and session_age <= self.policy.guide_play_sec:
                self._reset_hold_candidate()
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="startup_guiding_soft_duck",
                    target_gain=self.policy.gain_soft_duck,
                    confidence=0.0,
                    aggressiveness="low",
                )

            if (
                session_age >= self.policy.no_progress_hold_min_play_sec
                and playback.state == PlaybackState.PLAYING
            ):
                if self._hold_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.HOLD,
                        reason="no_progress_timeout",
                        target_gain=0.0,
                        confidence=0.0,
                        aggressiveness="medium",
                    )
            else:
                self._reset_hold_candidate()

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="waiting_for_progress",
                target_gain=self.policy.gain_following,
                confidence=0.0,
                aggressiveness="low",
            )

        lead_sec = playback.t_ref_heard_content_sec - progress.estimated_ref_time_sec
        tracking_good = (
            progress.confidence >= self.policy.min_confidence
            and progress.tracking_quality >= self.policy.tracking_quality_hold_min
        )

        if progress.tracking_mode in (TrackingMode.LOST, TrackingMode.REACQUIRING):
            self._reset_hold_candidate()
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            if speaking:
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="reacquire_soft_duck",
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.confidence,
                    aggressiveness="low",
                )
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="reacquire_keep_playing",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_following,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        if not tracking_good:
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            should_hold = (
                lead_sec >= self.policy.hold_if_lead_sec + 0.15
                and progress.progress_age_sec >= self.policy.low_confidence_hold_sec
                and playback.state == PlaybackState.PLAYING
            )
            if should_hold:
                if self._hold_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.HOLD,
                        reason="low_confidence_ahead_hold",
                        lead_sec=lead_sec,
                        target_gain=0.0,
                        confidence=progress.confidence,
                        aggressiveness="medium",
                    )
            else:
                self._reset_hold_candidate()

            return ControlDecision(
                action=ControlAction.SOFT_DUCK if speaking else ControlAction.NOOP,
                reason="low_confidence_soft_follow" if speaking else "low_confidence_keep_playing",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck if speaking else self.policy.gain_following,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        can_seek = (
            not self.disable_seek
            and progress.tracking_mode == TrackingMode.LOCKED
            and progress.recently_progressed
            and progress.active_speaking
            and progress.stable
            and progress.tracking_quality >= self.policy.tracking_quality_seek_min
            and progress.confidence >= self.policy.min_confidence
            and lead_sec <= self.policy.seek_if_lag_sec
            and (now_sec - self._last_seek_at_sec) >= self.policy.seek_cooldown_sec
        )
        if can_seek:
            if self._seek_ready(now_sec):
                self._last_seek_at_sec = now_sec
                self._reset_hold_candidate()
                self._reset_resume_candidate()
                target_time_sec = max(0.0, progress.estimated_ref_time_sec + self.policy.target_lead_sec)
                return ControlDecision(
                    action=ControlAction.SEEK,
                    reason="lagging_seek_forward",
                    target_time_sec=target_time_sec,
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.confidence,
                    aggressiveness="high",
                )
        else:
            self._reset_seek_candidate()

        hold_threshold = self.policy.hold_if_lead_sec
        if progress.active_speaking:
            hold_threshold += self.policy.hold_extra_lead_sec

        if playback.state == PlaybackState.HOLDING:
            hold_tracking_ok = (
                progress.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED)
                and progress.confidence >= max(0.58, self.policy.min_confidence - 0.08)
                and progress.tracking_quality >= max(0.54, self.policy.tracking_quality_hold_min - 0.04)
            )
            resume_condition = (
                (lead_sec <= self.policy.resume_if_lead_sec and hold_tracking_ok)
                or (
                    progress.active_speaking
                    and hold_tracking_ok
                    and lead_sec <= (
                        self.policy.resume_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec
                    )
                )
            )

            self._reset_hold_candidate()
            if resume_condition:
                if self._resume_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.RESUME,
                        reason="lead_recovered_resume" if lead_sec <= self.policy.resume_if_lead_sec else "speaking_resume_slack",
                        lead_sec=lead_sec,
                        target_gain=self.policy.gain_following,
                        confidence=progress.confidence,
                        aggressiveness="medium",
                    )
            else:
                self._reset_resume_candidate()

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="holding_wait_for_resume_window",
                lead_sec=lead_sec,
                target_gain=0.0,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        self._reset_resume_candidate()

        should_hold = (
            lead_sec >= hold_threshold
            and playback.state == PlaybackState.PLAYING
            and progress.tracking_quality >= self.policy.tracking_quality_hold_min
        )
        if should_hold:
            if self._hold_ready(now_sec):
                return ControlDecision(
                    action=ControlAction.HOLD,
                    reason="reference_too_far_ahead",
                    lead_sec=lead_sec,
                    target_gain=0.0,
                    confidence=progress.confidence,
                    aggressiveness="medium",
                )
        else:
            self._reset_hold_candidate()

        if lead_sec >= max(self.policy.target_lead_sec + 0.10, 0.35):
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="ahead_soft_duck",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_follow_band",
            lead_sec=lead_sec,
            target_gain=self.policy.gain_following,
            confidence=progress.confidence,
            aggressiveness="low",
        )

    def _is_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= 0.50
        )

    def _hold_ready(self, now_sec: float) -> bool:
        if self._hold_candidate_since_sec <= 0.0:
            self._hold_candidate_since_sec = now_sec
            return False
        return (now_sec - self._hold_candidate_since_sec) >= self._hold_hysteresis_sec

    def _resume_ready(self, now_sec: float) -> bool:
        if self._resume_candidate_since_sec <= 0.0:
            self._resume_candidate_since_sec = now_sec
            return False
        return (now_sec - self._resume_candidate_since_sec) >= self._resume_hysteresis_sec

    def _seek_ready(self, now_sec: float) -> bool:
        if self._seek_candidate_since_sec <= 0.0:
            self._seek_candidate_since_sec = now_sec
            return False
        return (now_sec - self._seek_candidate_since_sec) >= self._seek_hysteresis_sec

    def _reset_hold_candidate(self) -> None:
        self._hold_candidate_since_sec = 0.0

    def _reset_resume_candidate(self) -> None:
        self._resume_candidate_since_sec = 0.0

    def _reset_seek_candidate(self) -> None:
        self._seek_candidate_since_sec = 0.0