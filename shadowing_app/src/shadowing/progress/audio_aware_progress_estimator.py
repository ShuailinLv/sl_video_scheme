from __future__ import annotations
from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import ProgressEstimate, ReferenceMap, SignalQuality, TrackingMode, TrackingSnapshot, UserReadState


class AudioAwareProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
        min_tracking_for_follow: float = 0.58,
        audio_takeover_confidence: float = 0.66,
        audio_retain_confidence: float = 0.56,
        max_audio_pull_sec: float = 1.2,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)
        self.min_tracking_for_follow = float(min_tracking_for_follow)
        self.audio_takeover_confidence = float(audio_takeover_confidence)
        self.audio_retain_confidence = float(audio_retain_confidence)
        self.max_audio_pull_sec = float(max_audio_pull_sec)
        self.behavior_interpreter = BehaviorInterpreter(recent_progress_sec=recent_progress_sec)
        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0

    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_tracking = None
        self._last_snapshot = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0

    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80

    def update(self, *, tracking: TrackingSnapshot | None, audio_match, audio_behavior, signal_quality: SignalQuality | None, now_sec: float) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if tracking is not None:
            self._last_tracking = tracking
            self._last_event_at_sec = float(tracking.emitted_at_sec)
        current_idx = int(round(self._estimated_idx_f))
        text_candidate_idx = current_idx
        text_committed_idx = current_idx
        text_quality = 0.0
        text_conf = 0.0
        text_stable = False
        tracking_mode = TrackingMode.BOOTSTRAP
        if tracking is not None:
            text_candidate_idx = int(tracking.candidate_ref_idx)
            text_committed_idx = int(tracking.committed_ref_idx)
            text_quality = float(tracking.tracking_quality.overall_score)
            text_conf = float(tracking.confidence)
            text_stable = bool(tracking.stable)
            tracking_mode = tracking.tracking_mode
        audio_idx = current_idx
        audio_conf = 0.0
        audio_time_sec = None
        repeated = 0.0
        reentry = 0.0
        still_following = 0.0
        if audio_match is not None:
            audio_idx = max(0, min(int(getattr(audio_match, "estimated_ref_idx_hint", current_idx)), len(self._ref_map.tokens) - 1))
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            audio_time_sec = float(getattr(audio_match, "estimated_ref_time_sec", 0.0))
            repeated = float(getattr(audio_match, "repeated_pattern_score", 0.0))
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = float(getattr(audio_behavior, "still_following_likelihood", 0.0))
            repeated = max(repeated, float(getattr(audio_behavior, "repeated_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
        target_idx = float(max(current_idx, text_committed_idx))
        position_source = "text"
        if tracking is not None:
            weight = self._weight_for_tracking(tracking)
            target_idx = max(target_idx, (1.0 - weight) * self._estimated_idx_f + weight * float(max(text_candidate_idx, text_committed_idx)))
            if tracking.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED) and tracking.local_match_ratio >= 0.68 and text_candidate_idx > current_idx:
                target_idx = max(target_idx, float(current_idx) + 0.60)
        audio_can_assist = bool(audio_conf >= self.audio_retain_confidence and still_following >= 0.58 and repeated < 0.82)
        audio_can_takeover = bool(audio_conf >= self.audio_takeover_confidence and still_following >= 0.64 and (tracking is None or text_quality < 0.56 or tracking_mode in (TrackingMode.REACQUIRING, TrackingMode.LOST)))
        if audio_can_assist:
            audio_push = max(0, audio_idx - current_idx)
            if audio_push > 0:
                target_idx = max(target_idx, float(current_idx) + min(2.0, 0.45 + 0.35 * min(audio_push, 4)))
                self._last_audio_progress_at_sec = float(now_sec)
                position_source = "joint"
        if audio_can_takeover:
            target_idx = max(target_idx, float(audio_idx))
            self._last_audio_progress_at_sec = float(now_sec)
            position_source = "audio"
        estimated_idx = max(0, min(int(round(target_idx)), len(self._ref_map.tokens) - 1))
        progressed = estimated_idx > current_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and now_sec > self._last_progress_at_sec:
                dt = max(1e-6, now_sec - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = float(now_sec)
            self._last_estimated_idx_at_progress = float(estimated_idx)
        self._estimated_idx_f = float(estimated_idx)
        self._last_snapshot = self._render_snapshot(now_sec=now_sec, signal_quality=signal_quality, audio_conf=audio_conf, still_following=still_following, reentry=reentry, position_source=position_source)
        return self._last_snapshot

    def snapshot(self, *, now_sec: float, signal_quality: SignalQuality | None, audio_match=None, audio_behavior=None) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        audio_conf = 0.0
        still_following = 0.0
        reentry = 0.0
        position_source = "text"
        if audio_match is not None:
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = float(getattr(audio_behavior, "still_following_likelihood", 0.0))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            if audio_conf >= self.audio_retain_confidence:
                position_source = "joint"
        self._last_snapshot = self._render_snapshot(now_sec=now_sec, signal_quality=signal_quality, audio_conf=audio_conf, still_following=still_following, reentry=reentry, position_source=position_source)
        return self._last_snapshot

    def _weight_for_tracking(self, tracking: TrackingSnapshot) -> float:
        if tracking.tracking_mode == TrackingMode.LOCKED:
            return 0.82 if tracking.stable else 0.68
        if tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            return 0.42
        if tracking.tracking_mode == TrackingMode.REACQUIRING:
            return 0.16
        return 0.05

    def _render_snapshot(self, *, now_sec: float, signal_quality: SignalQuality | None, audio_conf: float, still_following: float, reentry: float, position_source: str) -> ProgressEstimate:
        assert self._ref_map is not None
        tracking = self._last_tracking
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)
        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)
        if self._last_audio_progress_at_sec > 0.0 and audio_conf >= self.audio_retain_confidence:
            progress_age = min(progress_age, max(0.0, now_sec - self._last_audio_progress_at_sec))
        recently_progressed = progress_age <= self.recent_progress_sec
        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = signal_quality.vad_active or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
        tracking_mode = TrackingMode.BOOTSTRAP
        tracking_quality = 0.0
        confidence = 0.0
        stable = False
        source_candidate_ref_idx = estimated_idx
        source_committed_ref_idx = estimated_idx
        event_emitted_at_sec = self._last_event_at_sec
        if tracking is not None:
            tracking_mode = tracking.tracking_mode
            tracking_quality = tracking.tracking_quality.overall_score
            confidence = tracking.confidence
            stable = tracking.stable
            source_candidate_ref_idx = tracking.candidate_ref_idx
            source_committed_ref_idx = tracking.committed_ref_idx
        if now_sec <= self._force_reacquire_until_sec:
            tracking_mode = TrackingMode.REACQUIRING
            tracking_quality = min(tracking_quality, 0.55)
        active_speaking = False
        if recently_progressed:
            active_speaking = True
        elif signal_speaking and tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            active_speaking = True
        elif signal_speaking and tracking_quality >= 0.70:
            active_speaking = True
        elif audio_conf >= self.audio_retain_confidence and (still_following >= 0.62 or reentry >= 0.58):
            active_speaking = True
        joint_conf = max(confidence, 0.55 * confidence + 0.45 * audio_conf, 0.52 * tracking_quality + 0.48 * audio_conf)
        if audio_conf >= self.audio_takeover_confidence and joint_conf < audio_conf:
            joint_conf = 0.92 * audio_conf
        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=tracking,
            tracking_mode=tracking_mode,
            tracking_quality=max(tracking_quality, audio_conf * 0.82),
            candidate_idx=max(source_candidate_ref_idx, estimated_idx),
            estimated_idx=estimated_idx,
        )
        if audio_conf >= self.audio_takeover_confidence and still_following >= 0.62 and user_state in (UserReadState.NOT_STARTED, UserReadState.PAUSED):
            user_state = UserReadState.FOLLOWING
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            progress_velocity_idx_per_sec=float(self._last_velocity),
            event_emitted_at_sec=float(event_emitted_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_age_sec=float(progress_age),
            source_candidate_ref_idx=int(source_candidate_ref_idx),
            source_committed_ref_idx=int(source_committed_ref_idx),
            tracking_mode=tracking_mode,
            tracking_quality=float(max(tracking_quality, audio_conf * 0.72 if position_source != "text" else tracking_quality)),
            stable=bool(stable),
            confidence=float(max(confidence, audio_conf * 0.80 if position_source == "audio" else confidence)),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
            audio_confidence=float(audio_conf),
            joint_confidence=float(max(0.0, min(1.0, joint_conf))),
            position_source=str(position_source),
            audio_support_strength=float(max(still_following, reentry, audio_conf)),
        )
