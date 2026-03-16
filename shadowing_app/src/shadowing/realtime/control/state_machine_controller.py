from __future__ import annotations

import time
from dataclasses import dataclass

from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.sync_evidence import SyncEvidence, SyncState, TrackingState
from shadowing.types import ControlAction, ControlDecision, FusionEvidence, PlaybackState


@dataclass(slots=True)
class _PressureState:
    hold_pressure: float = 0.0
    resume_pressure: float = 0.0
    seek_pressure: float = 0.0
    soft_duck_pressure: float = 0.0
    lead_ema: float = 0.0
    tracking_quality_ema: float = 0.0
    confidence_ema: float = 0.0
    speech_confidence_ema: float = 0.0
    last_tick_at: float = 0.0


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

        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)

    def reset(self) -> None:
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)

    def decide(
        self,
        playback,
        progress,
        signal_quality,
        sync_evidence: SyncEvidence | None = None,
        fusion_evidence: FusionEvidence | None = None,
    ) -> ControlDecision:
        now = time.monotonic()

        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        fusion_fused_conf = 0.0 if fusion_evidence is None else float(fusion_evidence.fused_confidence)

        # 关键改动：当文本 progress 还没起来，但音频辅助已明显成立时，用 audio surrogate 驱动控制。
        if progress is None:
            if fusion_evidence is None or max(fusion_fused_conf, fusion_still_following) < 0.60:
                return ControlDecision(
                    action=ControlAction.NOOP,
                    reason="no_progress",
                    target_gain=self._gain_for_state(playback.state, following=False),
                    confidence=0.0,
                )
            effective_idx = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
            tracking_quality = max(0.0, min(1.0, fusion_fused_conf * 0.86))
            confidence = fusion_fused_conf
            active_speaking = bool(fusion_still_following >= 0.62 or fusion_reentry >= 0.58)
            recently_progressed = False
            progress_age_sec = 9999.0
            estimated_ref_time_sec = float(fusion_evidence.estimated_ref_time_sec)
            stable = bool(fusion_fused_conf >= 0.72)
        else:
            effective_idx = int(getattr(progress, "estimated_ref_idx", 0))
            tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
            confidence = float(getattr(progress, "confidence", 0.0))
            active_speaking = bool(getattr(progress, "active_speaking", False))
            recently_progressed = bool(getattr(progress, "recently_progressed", False))
            progress_age_sec = float(getattr(progress, "progress_age_sec", 9999.0))
            estimated_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            stable = bool(getattr(progress, "stable", False))

        if active_speaking or recently_progressed or fusion_still_following >= 0.66 or fusion_reentry >= 0.58:
            self._last_voice_like_at = now

        if effective_idx > self._last_effective_idx:
            self._last_effective_idx = effective_idx

        in_startup_grace = (now - self._started_at) < self.policy.startup_grace_sec
        in_resume_cooldown = (now - self._last_resume_at) < 0.35
        in_seek_cooldown = (now - self._last_seek_at) < self.policy.seek_cooldown_sec
        in_soft_duck_cooldown = (now - self._last_soft_duck_at) < 0.25
        speaking_recent = (now - self._last_voice_like_at) <= self.policy.speaking_recent_sec
        progress_stale = progress_age_sec >= self.policy.progress_stale_sec

        playback_ref = float(playback.t_ref_heard_content_sec)
        if fusion_evidence is not None and fusion_evidence.fused_confidence >= 0.58 and tracking_quality < 0.55:
            user_ref = float(fusion_evidence.estimated_ref_time_sec)
        else:
            user_ref = float(estimated_ref_time_sec)

        lead_sec = playback_ref - user_ref

        speech_conf = 0.0
        tracking_state = TrackingState.NONE
        sync_state = SyncState.BOOTSTRAP
        allow_seek = False
        bluetooth_mode = False
        if sync_evidence is not None:
            speech_conf = float(sync_evidence.speech_confidence)
            tracking_state = sync_evidence.tracking_state
            sync_state = sync_evidence.sync_state
            allow_seek = bool(sync_evidence.allow_seek)
            bluetooth_mode = bool(sync_evidence.bluetooth_mode)

        dt = max(0.01, now - self._pressure.last_tick_at)
        self._pressure.last_tick_at = now

        self._update_emas(
            lead_sec=lead_sec,
            tracking_quality=tracking_quality,
            confidence=confidence,
            speech_confidence=speech_conf,
        )

        weak_resume_ok = bool(
            (
                active_speaking
                or fusion_reentry >= 0.60
                or fusion_still_following >= 0.72
            )
            and tracking_quality >= self.policy.tracking_quality_hold_min - 0.05
            and confidence >= max(0.56, self.policy.min_confidence - 0.16)
            and speaking_recent
        )

        strong_resume_ok = bool(
            (recently_progressed or active_speaking or fusion_reentry >= 0.65 or fusion_still_following >= 0.76)
            and tracking_quality >= self.policy.tracking_quality_hold_min
            and confidence >= self.policy.min_confidence - (0.08 if fusion_still_following >= 0.72 else 0.0)
        )

        following = (
            strong_resume_ok
            or weak_resume_ok
            or tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED)
            or fusion_still_following >= 0.72
        )

        self._update_pressures(
            dt=dt,
            playback_state=playback.state,
            lead_sec=lead_sec,
            progress_stale=progress_stale,
            tracking_quality=tracking_quality,
            confidence=confidence,
            stable=stable,
            speaking_recent=speaking_recent,
            in_startup_grace=in_startup_grace,
            strong_resume_ok=strong_resume_ok,
            weak_resume_ok=weak_resume_ok,
            in_resume_cooldown=in_resume_cooldown,
            in_seek_cooldown=in_seek_cooldown,
            allow_seek=allow_seek and (not self.disable_seek),
            tracking_state=tracking_state,
            sync_state=sync_state,
            bluetooth_mode=bluetooth_mode,
            fusion_evidence=fusion_evidence,
        )

        # 关键改动：音频证据强时，硬压 hold / seek 压力
        if fusion_evidence is not None:
            if fusion_evidence.should_prevent_hold:
                self._pressure.hold_pressure *= 0.18
                self._pressure.soft_duck_pressure *= 0.72
            if fusion_evidence.should_prevent_seek:
                self._pressure.seek_pressure *= 0.12
            if playback.state == PlaybackState.HOLDING and (
                fusion_still_following >= 0.74 or fusion_reentry >= 0.60
            ):
                self._pressure.resume_pressure = max(self._pressure.resume_pressure, 1.04)

        if playback.state == PlaybackState.HOLDING and self._pressure.resume_pressure >= 1.0:
            self._last_resume_at = now
            self._pressure.hold_pressure *= 0.25
            self._pressure.resume_pressure = 0.0
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="resume_pressure",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_following,
                confidence=max(confidence, fusion_still_following * 0.88, fusion_fused_conf * 0.82),
                aggressiveness="medium",
            )

        if playback.state == PlaybackState.PLAYING and self._pressure.hold_pressure >= 1.0:
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="hold_pressure",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck,
                confidence=confidence,
                aggressiveness="medium",
            )

        if (
            playback.state in (PlaybackState.PLAYING, PlaybackState.HOLDING)
            and self._pressure.seek_pressure >= 1.0
            and not self.disable_seek
            and allow_seek
            and fusion_repeated < 0.55
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        ):
            self._last_seek_at = now
            self._pressure.seek_pressure = 0.0
            self._pressure.hold_pressure *= 0.3
            target_time_sec = max(0.0, user_ref - self.policy.target_lead_sec)
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="seek_pressure",
                target_time_sec=target_time_sec,
                lead_sec=lead_sec,
                target_gain=self.policy.gain_transition,
                confidence=max(confidence, 0.35 + 0.45 * fusion_still_following),
                aggressiveness="low" if bluetooth_mode else "medium",
            )

        if (
            playback.state == PlaybackState.PLAYING
            and self._pressure.soft_duck_pressure >= 0.65
            and not in_soft_duck_cooldown
        ):
            self._last_soft_duck_at = now
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="soft_duck_pressure",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck,
                confidence=max(confidence, fusion_still_following * 0.62),
                aggressiveness="low",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="no_state_change",
            lead_sec=lead_sec,
            target_gain=self._gain_for_state(playback.state, following=following),
            confidence=max(confidence, fusion_still_following * 0.58, fusion_fused_conf * 0.52),
            aggressiveness="low",
        )

    def _update_emas(
        self,
        *,
        lead_sec: float,
        tracking_quality: float,
        confidence: float,
        speech_confidence: float,
    ) -> None:
        alpha = 0.22
        self._pressure.lead_ema = (1.0 - alpha) * self._pressure.lead_ema + alpha * float(lead_sec)
        self._pressure.tracking_quality_ema = (
            (1.0 - alpha) * self._pressure.tracking_quality_ema + alpha * float(tracking_quality)
        )
        self._pressure.confidence_ema = (
            (1.0 - alpha) * self._pressure.confidence_ema + alpha * float(confidence)
        )
        self._pressure.speech_confidence_ema = (
            (1.0 - alpha) * self._pressure.speech_confidence_ema + alpha * float(speech_confidence)
        )

    def _update_pressures(
        self,
        *,
        dt: float,
        playback_state,
        lead_sec: float,
        progress_stale: bool,
        tracking_quality: float,
        confidence: float,
        stable: bool,
        speaking_recent: bool,
        in_startup_grace: bool,
        strong_resume_ok: bool,
        weak_resume_ok: bool,
        in_resume_cooldown: bool,
        in_seek_cooldown: bool,
        allow_seek: bool,
        tracking_state: TrackingState,
        sync_state: SyncState,
        bluetooth_mode: bool,
        fusion_evidence: FusionEvidence | None,
    ) -> None:
        decay = 0.82 ** max(1.0, dt * 15.0)
        self._pressure.hold_pressure *= decay
        self._pressure.resume_pressure *= decay
        self._pressure.seek_pressure *= decay
        self._pressure.soft_duck_pressure *= decay

        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)

        if playback_state == PlaybackState.PLAYING:
            hold_scale = 0.45 if fusion_still_following >= 0.65 or fusion_reentry >= 0.58 else 1.0

            if not in_startup_grace and progress_stale and not speaking_recent:
                self._pressure.hold_pressure += 0.42 * hold_scale

            if not in_startup_grace and progress_stale and tracking_quality < self.policy.tracking_quality_hold_min:
                self._pressure.hold_pressure += 0.36 * hold_scale

            if lead_sec >= self.policy.hold_if_lead_sec:
                self._pressure.hold_pressure += 0.30 * hold_scale

            if tracking_state == TrackingState.WEAK or sync_state == SyncState.DEGRADED:
                self._pressure.soft_duck_pressure += 0.22

            if confidence < max(0.55, self.policy.min_confidence - 0.15):
                self._pressure.soft_duck_pressure += 0.10

            if stable and tracking_quality >= 0.76:
                self._pressure.hold_pressure *= 0.94

        if playback_state == PlaybackState.HOLDING and not in_resume_cooldown:
            if strong_resume_ok:
                self._pressure.resume_pressure += 0.48
            elif weak_resume_ok:
                self._pressure.resume_pressure += 0.28

            if fusion_reentry >= 0.62:
                self._pressure.resume_pressure += 0.24
            elif fusion_still_following >= 0.74:
                self._pressure.resume_pressure += 0.18

        seek_trigger = bool(
            allow_seek
            and not in_seek_cooldown
            and playback_state == PlaybackState.PLAYING
            and lead_sec <= self.policy.seek_if_lag_sec
            and tracking_quality >= self.policy.tracking_quality_seek_min
            and confidence >= max(0.70, self.policy.min_confidence)
            and tracking_state == TrackingState.LOCKED
            and sync_state == SyncState.STABLE
            and fusion_repeated < 0.60
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        )
        if seek_trigger:
            self._pressure.seek_pressure += 0.24 if bluetooth_mode else 0.34

        self._pressure.hold_pressure = max(0.0, min(1.4, self._pressure.hold_pressure))
        self._pressure.resume_pressure = max(0.0, min(1.4, self._pressure.resume_pressure))
        self._pressure.seek_pressure = max(0.0, min(1.4, self._pressure.seek_pressure))
        self._pressure.soft_duck_pressure = max(0.0, min(1.2, self._pressure.soft_duck_pressure))

    def _gain_for_state(self, state, *, following: bool) -> float:
        if state == PlaybackState.HOLDING:
            return self.policy.gain_soft_duck
        if following:
            return self.policy.gain_following
        return self.policy.gain_transition