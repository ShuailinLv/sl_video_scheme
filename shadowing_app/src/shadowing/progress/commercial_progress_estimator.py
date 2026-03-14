from __future__ import annotations

from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import (
    ProgressEstimate,
    ReferenceMap,
    SignalQuality,
    TrackingMode,
    TrackingSnapshot,
)


class CommercialProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
        min_tracking_for_follow: float = 0.58,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)
        self.min_tracking_for_follow = float(min_tracking_for_follow)

        self.behavior_interpreter = BehaviorInterpreter(
            recent_progress_sec=recent_progress_sec,
        )

        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0

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

    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80

    def update(
        self,
        tracking: TrackingSnapshot | None,
        signal_quality: SignalQuality | None,
        now_sec: float,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None

        if tracking is None:
            return self.snapshot(now_sec, signal_quality)

        self._last_tracking = tracking
        self._last_event_at_sec = float(tracking.emitted_at_sec)

        current_idx = int(round(self._estimated_idx_f))
        candidate_idx = int(tracking.candidate_ref_idx)
        committed_idx = int(tracking.committed_ref_idx)
        target_idx = float(max(current_idx, committed_idx, candidate_idx))

        weight = self._weight_for_tracking(tracking)
        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )

        if (
            tracking.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED)
            and tracking.local_match_ratio >= 0.68
            and candidate_idx > current_idx
        ):
            updated_idx = max(updated_idx, float(current_idx) + 0.60)

        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)

        progressed = estimated_idx > current_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and tracking.emitted_at_sec > self._last_progress_at_sec:
                dt = max(1e-6, tracking.emitted_at_sec - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = float(tracking.emitted_at_sec)
            self._last_estimated_idx_at_progress = float(estimated_idx)

        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot

    def snapshot(self, now_sec: float, signal_quality: SignalQuality | None) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_tracking is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot

    def _weight_for_tracking(self, tracking: TrackingSnapshot) -> float:
        if tracking.tracking_mode == TrackingMode.LOCKED:
            return 0.82 if tracking.stable else 0.68
        if tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            return 0.42
        if tracking.tracking_mode == TrackingMode.REACQUIRING:
            return 0.16
        return 0.05

    def _render_snapshot(
        self,
        now_sec: float,
        signal_quality: SignalQuality | None,
    ) -> ProgressEstimate:
        assert self._ref_map is not None

        tracking = self._last_tracking
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)

        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)

        recently_progressed = progress_age <= self.recent_progress_sec

        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = (
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )

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

        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=tracking,
            tracking_mode=tracking_mode,
            tracking_quality=tracking_quality,
            candidate_idx=source_candidate_ref_idx,
            estimated_idx=estimated_idx,
        )

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
            tracking_quality=float(tracking_quality),
            stable=bool(stable),
            confidence=float(confidence),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
        )