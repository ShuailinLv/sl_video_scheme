from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.types import (
    ControlAction,
    ControlDecision,
    PlaybackStatus,
    ProgressEstimate,
    SignalQuality,
    TrackingMode,
    UserReadState,
)


class StateMachineController(Controller):
    def __init__(
        self,
        policy: ControlPolicy | None = None,
        total_duration_sec: float | None = None,
        disable_seek: bool = False,
    ) -> None:
        self.policy = policy or ControlPolicy()
        self.total_duration_sec = total_duration_sec
        self.disable_seek = bool(disable_seek)

        self._last_seek_at = 0.0
        self._session_started_at = time.monotonic()

        self._phase = "bootstrapping"
        self._hold_condition_started_at = 0.0
        self._last_good_progress_at = 0.0

        self._last_decision_log_at = 0.0
        self._last_decision_signature = ""
        self._decision_log_interval_sec = 1.20

    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision:
        now = time.monotonic()

        if playback.state.value == "playing" and playback.t_ref_emitted_content_sec <= 0.05:
            self._session_started_at = now

        if progress is not None and progress.tracking_quality >= self.policy.tracking_quality_hold_min:
            self._last_good_progress_at = now

        self._update_phase(now, progress, signal_quality)

        if progress is None:
            decision = self._decide_without_progress(playback, signal_quality, now)
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        lead = playback.t_ref_heard_content_sec - progress.estimated_ref_time_sec

        if self._is_in_seek_recovery(now):
            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="recover_after_seek",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
                confidence=progress.tracking_quality,
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if playback.state.value == "holding":
            if self._should_resume_from_hold(lead, progress, signal_quality, now):
                decision = ControlDecision(
                    action=ControlAction.RESUME,
                    reason="rejoin_resume",
                    lead_sec=lead,
                    target_gain=self.policy.gain_following,
                    confidence=progress.tracking_quality,
                    aggressiveness="medium",
                )
                self._hold_condition_started_at = 0.0
                self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
                return decision

            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="holding_wait",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._phase in ("bootstrapping", "guiding"):
            if self._signal_active(signal_quality):
                decision = ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="guide_soft_duck",
                    lead_sec=lead,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.tracking_quality,
                    aggressiveness="low",
                )
            else:
                decision = ControlDecision(
                    action=ControlAction.NOOP,
                    reason="guide_play",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.tracking_quality,
                )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._phase in ("uncertain_follow", "reacquiring"):
            if lead > (self.policy.hold_if_lead_sec + self.policy.hold_extra_lead_sec):
                decision = ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="reacquire_soft_duck",
                    lead_sec=lead,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.tracking_quality,
                    aggressiveness="low",
                )
            else:
                decision = ControlDecision(
                    action=ControlAction.NOOP,
                    reason="uncertain_follow_keep_playing",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.tracking_quality,
                )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._should_hold(playback, progress, signal_quality, lead, now):
            decision = ControlDecision(
                action=ControlAction.HOLD,
                reason="reference_too_far_ahead",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
                aggressiveness="medium",
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._should_seek(progress, lead, now):
            target_time = progress.estimated_ref_time_sec + self.policy.target_lead_sec
            if self.total_duration_sec is not None:
                target_time = min(max(0.0, target_time), self.total_duration_sec)
            else:
                target_time = max(0.0, target_time)

            self._last_seek_at = now
            decision = ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=target_time,
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
                aggressiveness="high",
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        decision = ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead,
            target_gain=self.policy.gain_following,
            confidence=progress.tracking_quality,
        )
        self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
        return decision

    def _update_phase(
        self,
        now: float,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> None:
        elapsed = now - self._session_started_at

        if progress is None:
            if elapsed < self.policy.bootstrapping_sec:
                self._phase = "bootstrapping"
                return
            if elapsed < self.policy.no_progress_hold_min_play_sec:
                self._phase = "guiding"
                return
            self._phase = "waiting"
            return

        if progress.tracking_mode == TrackingMode.LOST:
            self._phase = "reacquiring"
            return

        if progress.tracking_mode == TrackingMode.REACQUIRING:
            self._phase = "reacquiring"
            return

        if elapsed < self.policy.bootstrapping_sec:
            self._phase = "bootstrapping"
            return

        if elapsed < self.policy.guide_play_sec and progress.user_state in (
            UserReadState.WARMING_UP,
            UserReadState.HESITATING,
            UserReadState.NOT_STARTED,
        ):
            self._phase = "guiding"
            return

        if progress.user_state in (UserReadState.REJOINING, UserReadState.SKIPPING):
            self._phase = "reacquiring"
            return

        if progress.user_state == UserReadState.FOLLOWING and progress.tracking_quality >= self.policy.tracking_quality_hold_min:
            self._phase = "following"
            return

        if progress.user_state in (
            UserReadState.WARMING_UP,
            UserReadState.HESITATING,
            UserReadState.REPEATING,
        ):
            self._phase = "uncertain_follow"
            return

        if progress.user_state in (
            UserReadState.PAUSED,
            UserReadState.NOT_STARTED,
        ):
            self._phase = "waiting"
            return

        if self._signal_active(signal_quality):
            self._phase = "uncertain_follow"
            return

        self._phase = "waiting"

    def _decide_without_progress(
        self,
        playback: PlaybackStatus,
        signal_quality: SignalQuality | None,
        now: float,
    ) -> ControlDecision:
        elapsed = now - self._session_started_at

        if elapsed < self.policy.bootstrapping_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="bootstrapping",
                target_gain=self.policy.gain_transition,
                aggressiveness="low",
            )

        if elapsed < self.policy.no_progress_hold_min_play_sec:
            if self._signal_active(signal_quality):
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="guiding_soft_duck_no_progress",
                    target_gain=self.policy.gain_soft_duck,
                    aggressiveness="low",
                )
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="guiding_no_progress",
                target_gain=self.policy.gain_transition,
            )

        stale_good = self._stale_good_progress_sec(now)

        if playback.state.value == "holding":
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="waiting_for_progress",
                target_gain=self.policy.gain_following,
            )

        if self._signal_active(signal_quality):
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="no_progress_but_signal_active",
                target_gain=self.policy.gain_soft_duck,
                aggressiveness="low",
            )

        if stale_good < self.policy.low_confidence_continue_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="keep_playing_recent_good_progress",
                target_gain=self.policy.gain_transition,
            )

        if playback.t_ref_heard_content_sec > (self.policy.hold_if_lead_sec + self.policy.hold_extra_lead_sec):
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="no_progress_timeout",
                target_gain=self.policy.gain_following,
                aggressiveness="medium",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="wait_progress_soft",
            target_gain=self.policy.gain_transition,
        )

    def _should_resume_from_hold(
        self,
        lead: float,
        progress: ProgressEstimate,
        signal_quality: SignalQuality | None,
        now: float,
    ) -> bool:
        if lead <= self.policy.resume_if_lead_sec:
            return True

        signal_active = self._signal_active(signal_quality)
        event_fresh = (now - progress.event_emitted_at_sec) <= self.policy.resume_from_hold_event_fresh_sec

        if progress.user_state in (UserReadState.REJOINING, UserReadState.FOLLOWING):
            if event_fresh and signal_active:
                if lead <= (self.policy.hold_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec):
                    return True

        if progress.active_speaking and event_fresh:
            if lead <= (self.policy.hold_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec):
                return True

        if progress.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            if progress.recently_progressed and lead <= (self.policy.resume_if_lead_sec + 0.18):
                return True

        return False

    def _should_hold(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate,
        signal_quality: SignalQuality | None,
        lead: float,
        now: float,
    ) -> bool:
        if self._phase not in ("following", "waiting"):
            self._hold_condition_started_at = 0.0
            return False

        if progress.tracking_quality < self.policy.tracking_quality_hold_min:
            self._hold_condition_started_at = 0.0
            return False

        if progress.active_speaking or self._signal_active(signal_quality):
            self._hold_condition_started_at = 0.0
            return False

        hold_threshold = self.policy.hold_if_lead_sec
        if progress.confidence < self.policy.min_confidence:
            hold_threshold += self.policy.hold_extra_lead_sec

        if lead <= hold_threshold:
            self._hold_condition_started_at = 0.0
            return False

        if progress.progress_age_sec < self.policy.progress_stale_sec:
            self._hold_condition_started_at = 0.0
            return False

        if self._hold_condition_started_at <= 0.0:
            self._hold_condition_started_at = now
            return False

        if (now - self._hold_condition_started_at) < self.policy.hold_trend_sec:
            return False

        return True

    def _should_seek(self, progress: ProgressEstimate, lead: float, now: float) -> bool:
        if self.disable_seek:
            return False
        if progress.tracking_mode != TrackingMode.LOCKED:
            return False
        if progress.tracking_quality < self.policy.tracking_quality_seek_min:
            return False
        if not progress.stable:
            return False
        if lead >= self.policy.seek_if_lag_sec:
            return False
        if (now - self._last_seek_at) < self.policy.seek_cooldown_sec:
            return False
        return True

    def _signal_active(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= 0.48
        )

    def _stale_good_progress_sec(self, now: float) -> float:
        if self._last_good_progress_at <= 0:
            return float("inf")
        return now - self._last_good_progress_at

    def _is_in_seek_recovery(self, now_sec: float) -> bool:
        return (now_sec - self._last_seek_at) < self.policy.recover_after_seek_sec

    def _log_decision_if_needed(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
        decision: ControlDecision,
        now: float,
    ) -> None:
        lead_str = "None" if decision.lead_sec is None else f"{decision.lead_sec:.3f}"
        conf_str = "None" if progress is None else f"{progress.confidence:.3f}"
        tq_str = "None" if progress is None else f"{progress.tracking_quality:.3f}"
        est_idx_str = "None" if progress is None else str(progress.estimated_ref_idx)
        mode_str = "None" if progress is None else progress.tracking_mode.value
        user_state_str = "None" if progress is None else progress.user_state.value
        signal_str = "None" if signal_quality is None else f"{signal_quality.speaking_likelihood:.2f}"

        signature = (
            f"{self._phase}|{playback.state.value}|{decision.action.value}|{decision.reason}|"
            f"{lead_str}|{conf_str}|{tq_str}|{est_idx_str}|{mode_str}|{user_state_str}|{signal_str}"
        )

        should_log = False
        if signature != self._last_decision_signature:
            should_log = True
        elif decision.action in (
            ControlAction.HOLD,
            ControlAction.RESUME,
            ControlAction.SEEK,
            ControlAction.SOFT_DUCK,
        ):
            should_log = True
        elif (now - self._last_decision_log_at) >= self._decision_log_interval_sec:
            should_log = True

        if not should_log:
            return

        print(
            "[CTRL] "
            f"phase={self._phase} "
            f"playback={playback.state.value} "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"progress_conf={conf_str} "
            f"tracking_q={tq_str} "
            f"mode={mode_str} "
            f"user_state={user_state_str} "
            f"signal={signal_str} "
            f"estimated={est_idx_str}"
        )

        self._last_decision_signature = signature
        self._last_decision_log_at = now