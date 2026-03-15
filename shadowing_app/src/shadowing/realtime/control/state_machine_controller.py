from __future__ import annotations

import time

from shadowing.realtime.control.policy import ControlPolicy
from shadowing.types import ControlAction, ControlDecision, PlaybackState


class StateMachineController:
    def __init__(
        self,
        *,
        policy: ControlPolicy,
        disable_seek: bool = False,
        debug: bool = False,
    ) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek)
        self.debug = bool(debug)

        self._started_at = time.monotonic()
        self._last_resume_at = self._started_at
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_voice_like_at = self._started_at
        self._last_progress_at = self._started_at
        self._last_effective_idx = 0

    def reset(self) -> None:
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_voice_like_at = now
        self._last_progress_at = now
        self._last_effective_idx = 0

    def decide(self, playback, progress, signal_quality) -> ControlDecision:
        now = time.monotonic()

        if progress is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_progress",
                target_gain=self._gain_for_state(playback.state, following=False),
                confidence=0.0,
            )

        effective_idx = int(getattr(progress, "estimated_ref_idx", 0))
        tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
        confidence = float(getattr(progress, "confidence", 0.0))
        active_speaking = bool(getattr(progress, "active_speaking", False))
        recently_progressed = bool(getattr(progress, "recently_progressed", False))
        progress_age_sec = float(getattr(progress, "progress_age_sec", 9999.0))
        estimated_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
        tracking_mode = getattr(progress, "tracking_mode", None)

        if active_speaking or recently_progressed:
            self._last_voice_like_at = now

        if effective_idx > self._last_effective_idx:
            self._last_progress_at = now
            self._last_effective_idx = effective_idx

        in_startup_grace = (now - self._started_at) < self.policy.startup_grace_sec
        in_resume_cooldown = (now - self._last_resume_at) < 0.25
        in_seek_cooldown = (now - self._last_seek_at) < self.policy.seek_cooldown_sec

        speaking_recent = (now - self._last_voice_like_at) <= self.policy.speaking_recent_sec
        progress_stale = progress_age_sec >= self.policy.progress_stale_sec

        playback_ref = float(playback.t_ref_heard_content_sec)
        user_ref = float(estimated_ref_time_sec)
        lead_sec = playback_ref - user_ref

        weak_resume_ok = bool(
            active_speaking
            and tracking_quality >= self.policy.tracking_quality_hold_min
            and confidence >= max(0.62, self.policy.min_confidence - 0.12)
            and speaking_recent
        )

        strong_resume_ok = bool(
            (recently_progressed or active_speaking)
            and tracking_quality >= self.policy.tracking_quality_hold_min
            and confidence >= self.policy.min_confidence
        )

        following = strong_resume_ok or weak_resume_ok

        if (
            not in_startup_grace
            and not speaking_recent
            and playback.state == PlaybackState.PLAYING
            and progress_stale
        ):
            return self._hold(
                reason="silence_hold",
                lead_sec=lead_sec,
                gain=self.policy.gain_soft_duck,
                confidence=confidence,
            )

        if (
            not in_startup_grace
            and playback.state == PlaybackState.PLAYING
            and progress_stale
            and tracking_quality < self.policy.tracking_quality_hold_min
        ):
            return self._hold(
                reason="progress_stale",
                lead_sec=lead_sec,
                gain=self.policy.gain_soft_duck,
                confidence=confidence,
            )

        if playback.state == PlaybackState.PLAYING and lead_sec >= self.policy.hold_if_lead_sec:
            return self._hold(
                reason="reference_too_far_ahead",
                lead_sec=lead_sec,
                gain=self.policy.gain_soft_duck,
                confidence=confidence,
            )

        if (
            not self.disable_seek
            and playback.state in (PlaybackState.PLAYING, PlaybackState.HOLDING)
            and lead_sec <= self.policy.seek_if_lag_sec
            and tracking_quality >= self.policy.tracking_quality_seek_min
            and confidence >= max(0.66, self.policy.min_confidence - 0.06)
            and not in_seek_cooldown
        ):
            self._last_seek_at = now
            target_time_sec = max(0.0, user_ref - self.policy.target_lead_sec)
            action = ControlAction.SEEK
            reason = "seek_to_user_progress"
            if self.debug:
                print(
                    "[CTRL] "
                    f"action=seek reason={reason} lead_sec={lead_sec:.3f} "
                    f"target_time_sec={target_time_sec:.3f} tq={tracking_quality:.3f} conf={confidence:.3f}"
                )
            return ControlDecision(
                action=action,
                reason=reason,
                target_time_sec=target_time_sec,
                lead_sec=lead_sec,
                target_gain=self.policy.gain_transition,
                confidence=confidence,
                aggressiveness="medium",
            )

        if playback.state == PlaybackState.HOLDING:
            if strong_resume_ok and lead_sec <= (self.policy.resume_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec) and not in_resume_cooldown:
                self._last_resume_at = now
                if self.debug:
                    print(
                        "[CTRL] "
                        f"action=resume reason=strong_resume lead_sec={lead_sec:.3f} "
                        f"tq={tracking_quality:.3f} conf={confidence:.3f}"
                    )
                return ControlDecision(
                    action=ControlAction.RESUME,
                    reason="resume_strong_progress",
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_following,
                    confidence=confidence,
                    aggressiveness="medium",
                )

            if weak_resume_ok and lead_sec <= (self.policy.resume_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec) and not in_resume_cooldown:
                self._last_resume_at = now
                if self.debug:
                    mode_value = tracking_mode.value if tracking_mode is not None else "unknown"
                    print(
                        "[CTRL] "
                        f"action=resume reason=weak_resume lead_sec={lead_sec:.3f} "
                        f"mode={mode_value} tq={tracking_quality:.3f} conf={confidence:.3f}"
                    )
                return ControlDecision(
                    action=ControlAction.RESUME,
                    reason="resume_weak_progress",
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_following,
                    confidence=confidence,
                    aggressiveness="low",
                )

        gain = self._gain_for_state(playback.state, following=following)

        if tracking_mode is not None and tracking_mode.value == "reacquiring" and playback.state == PlaybackState.PLAYING:
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="reacquiring_soft_duck",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck,
                confidence=confidence,
                aggressiveness="low",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="no_state_change",
            lead_sec=lead_sec,
            target_gain=gain,
            confidence=confidence,
            aggressiveness="low",
        )

    def _hold(self, *, reason: str, lead_sec: float, gain: float, confidence: float) -> ControlDecision:
        self._last_hold_at = time.monotonic()
        if self.debug:
            print(
                "[CTRL] "
                f"action=hold reason={reason} lead_sec={lead_sec:.3f} confidence={confidence:.3f}"
            )
        return ControlDecision(
            action=ControlAction.HOLD,
            reason=reason,
            lead_sec=lead_sec,
            target_gain=gain,
            confidence=confidence,
            aggressiveness="medium",
        )

    def _gain_for_state(self, state, *, following: bool) -> float:
        if state == PlaybackState.HOLDING:
            return self.policy.gain_soft_duck
        if following:
            return self.policy.gain_following
        return self.policy.gain_transition