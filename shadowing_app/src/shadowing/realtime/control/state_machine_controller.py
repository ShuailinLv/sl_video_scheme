from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.types import AlignResult, ControlAction, ControlDecision, PlaybackStatus


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
        self._last_good_alignment_at = 0.0

        self._ever_resumed_or_played = False
        self._last_decision_log_at = 0.0
        self._last_decision_signature = ""
        self._last_alignment_ref_time_sec = 0.0

        self._no_alignment_keep_playing_sec = max(
            1.20,
            self.policy.startup_grace_sec + self.policy.low_confidence_hold_sec,
        )
        self._low_confidence_keep_playing_sec = max(
            1.50,
            self.policy.low_confidence_hold_sec + 0.60,
        )
        self._decision_log_interval_sec = 1.20

    def decide(self, playback: PlaybackStatus, alignment: AlignResult | None) -> ControlDecision:
        now = time.monotonic()

        if playback.state.value == "playing" and playback.t_ref_emitted_content_sec <= 0.05:
            self._session_started_at = now

        if playback.state.value == "playing":
            self._ever_resumed_or_played = True

        if alignment is not None and alignment.confidence >= self.policy.min_confidence:
            self._last_good_alignment_at = now
            self._last_alignment_ref_time_sec = alignment.ref_time_sec

        if alignment is None:
            decision = self._decide_without_alignment(playback, now)
            self._log_decision_if_needed(playback, alignment, decision, now)
            return decision

        if alignment.confidence < self.policy.min_confidence:
            decision = self._decide_low_confidence(playback, alignment, now)
            self._log_decision_if_needed(playback, alignment, decision, now)
            return decision

        lead = playback.t_ref_heard_content_sec - alignment.ref_time_sec

        if self._is_in_seek_recovery(now):
            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="recover_after_seek",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
            )
            self._log_decision_if_needed(playback, alignment, decision, now)
            return decision

        if playback.state.value == "holding":
            if lead <= self.policy.resume_if_lead_sec:
                decision = ControlDecision(
                    action=ControlAction.RESUME,
                    reason="user_caught_up",
                    lead_sec=lead,
                    target_gain=self.policy.gain_following,
                )
                self._log_decision_if_needed(playback, alignment, decision, now)
                return decision

            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="holding_wait",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
            )
            self._log_decision_if_needed(playback, alignment, decision, now)
            return decision

        if lead > self.policy.hold_if_lead_sec:
            decision = ControlDecision(
                action=ControlAction.HOLD,
                reason="reference_too_far_ahead",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
            )
            self._log_decision_if_needed(playback, alignment, decision, now)
            return decision

        if not self.disable_seek:
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
                decision = ControlDecision(
                    action=ControlAction.SEEK,
                    reason="user_skipped_forward",
                    target_time_sec=target_time,
                    lead_sec=lead,
                    target_gain=self.policy.gain_following,
                )
                self._log_decision_if_needed(playback, alignment, decision, now)
                return decision

        decision = ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead,
            target_gain=self.policy.gain_following if alignment.stable else self.policy.gain_transition,
        )
        self._log_decision_if_needed(playback, alignment, decision, now)
        return decision

    def _decide_without_alignment(self, playback: PlaybackStatus, now: float) -> ControlDecision:
        elapsed_since_start = now - self._session_started_at

        if elapsed_since_start < self.policy.startup_grace_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="startup_grace",
                target_gain=self.policy.gain_transition,
            )

        stale_for = self._stale_good_alignment_sec(now)

        if playback.state.value == "holding":
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="waiting_for_alignment",
                target_gain=self.policy.gain_following,
            )

        if self._ever_resumed_or_played and stale_for < self._no_alignment_keep_playing_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="keep_playing_no_alignment",
                target_gain=self.policy.gain_transition,
            )

        return ControlDecision(
            action=ControlAction.HOLD,
            reason="waiting_for_alignment",
            target_gain=self.policy.gain_following,
        )

    def _decide_low_confidence(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult,
        now: float,
    ) -> ControlDecision:
        lead = playback.t_ref_heard_content_sec - alignment.ref_time_sec
        elapsed_since_start = now - self._session_started_at

        if elapsed_since_start < self.policy.startup_grace_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="startup_low_confidence_grace",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
            )

        stale_for = self._stale_good_alignment_sec(now)

        if playback.state.value == "holding":
            if lead <= self.policy.resume_if_lead_sec and alignment.candidate_ref_idx >= alignment.committed_ref_idx:
                return ControlDecision(
                    action=ControlAction.RESUME,
                    reason="low_confidence_but_caught_up",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                )

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="low_confidence_wait",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
            )

        if self._ever_resumed_or_played:
            if stale_for < self._low_confidence_keep_playing_sec and lead <= (self.policy.hold_if_lead_sec + 0.35):
                return ControlDecision(
                    action=ControlAction.NOOP,
                    reason="keep_playing_low_confidence",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                )

        if lead > (self.policy.hold_if_lead_sec + 0.20):
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="low_confidence_and_ref_ahead",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="low_confidence_keep_running",
            lead_sec=lead,
            target_gain=self.policy.gain_transition,
        )

    def _stale_good_alignment_sec(self, now: float) -> float:
        if self._last_good_alignment_at <= 0:
            return float("inf")
        return now - self._last_good_alignment_at

    def _is_in_seek_recovery(self, now_sec: float) -> bool:
        return (now_sec - self._last_seek_at) < self.policy.recover_after_seek_sec

    def _log_decision_if_needed(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
        decision: ControlDecision,
        now: float,
    ) -> None:
        lead_str = "None" if decision.lead_sec is None else f"{decision.lead_sec:.3f}"
        conf_str = "None" if alignment is None else f"{alignment.confidence:.3f}"
        cand_str = "None" if alignment is None else str(alignment.candidate_ref_idx)
        committed_str = "None" if alignment is None else str(alignment.committed_ref_idx)
        stable_str = "None" if alignment is None else str(alignment.stable)

        signature = (
            f"{playback.state.value}|{decision.action.value}|{decision.reason}|"
            f"{lead_str}|{conf_str}|{cand_str}|{committed_str}|{stable_str}"
        )

        should_log = False
        if signature != self._last_decision_signature:
            should_log = True
        elif decision.action in (ControlAction.HOLD, ControlAction.RESUME, ControlAction.SEEK):
            should_log = True
        elif (now - self._last_decision_log_at) >= self._decision_log_interval_sec:
            should_log = True

        if not should_log:
            return

        stale_good = self._stale_good_alignment_sec(now)
        stale_good_str = "inf" if stale_good == float("inf") else f"{stale_good:.2f}"

        print(
            "[CTRL] "
            f"playback={playback.state.value} "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"align_conf={conf_str} "
            f"stable={stable_str} "
            f"candidate={cand_str} "
            f"committed={committed_str} "
            f"stale_good={stale_good_str}"
        )

        self._last_decision_signature = signature
        self._last_decision_log_at = now