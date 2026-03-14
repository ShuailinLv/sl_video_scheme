from __future__ import annotations

from shadowing.types import AlignResult, ProgressEstimate, ReferenceMap


class MonotonicProgressEstimator:
    def __init__(
        self,
        active_speaking_confidence: float = 0.68,
        recent_progress_sec: float = 0.90,
        speaking_event_fresh_sec: float = 0.45,
        local_match_for_speaking: float = 0.65,
    ) -> None:
        self.active_speaking_confidence = float(active_speaking_confidence)
        self.recent_progress_sec = float(recent_progress_sec)
        self.speaking_event_fresh_sec = float(speaking_event_fresh_sec)
        self.local_match_for_speaking = float(local_match_for_speaking)

        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_source_candidate_idx = 0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_velocity = 0.0
        self._last_alignment: AlignResult | None = None
        self._last_snapshot: ProgressEstimate | None = None

    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_source_candidate_idx = start_idx
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_velocity = 0.0
        self._last_alignment = None
        self._last_snapshot = None

    def on_playback_generation_changed(self, start_idx: int | None = None) -> None:
        if self._ref_map is None:
            return
        idx = int(round(self._estimated_idx_f)) if start_idx is None else int(start_idx)
        self.reset(self._ref_map, start_idx=idx)

    def update(self, alignment: AlignResult | None) -> ProgressEstimate | None:
        if alignment is None or self._ref_map is None or not self._ref_map.tokens:
            return self._last_snapshot

        self._last_alignment = alignment

        event_time = float(alignment.emitted_at_sec)
        if event_time <= 0.0:
            event_time = self._last_event_at_sec

        candidate_idx = int(alignment.candidate_ref_idx)
        committed_idx = int(alignment.committed_ref_idx)
        current_estimated_idx = int(round(self._estimated_idx_f))
        target_idx = float(max(candidate_idx, committed_idx, current_estimated_idx))

        if alignment.stable:
            weight = 0.88
        elif alignment.confidence >= 0.90:
            weight = 0.72
        elif alignment.confidence >= 0.78:
            weight = 0.50
        else:
            weight = 0.26

        if candidate_idx < current_estimated_idx:
            target_idx = float(current_estimated_idx)
            weight = min(weight, 0.12)

        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )

        if alignment.local_match_ratio >= 0.70 and candidate_idx > current_estimated_idx:
            updated_idx = max(updated_idx, float(current_estimated_idx) + 0.60)

        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)

        progressed = estimated_idx > current_estimated_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and event_time > self._last_progress_at_sec:
                dt = max(1e-6, event_time - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = event_time
            self._last_estimated_idx_at_progress = float(estimated_idx)

        self._last_source_candidate_idx = candidate_idx
        self._last_event_at_sec = event_time
        self._last_snapshot = self._render_snapshot(now_sec=event_time)
        return self._last_snapshot

    def snapshot(self, now_sec: float) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_alignment is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec=now_sec)
        return self._last_snapshot

    def _render_snapshot(self, now_sec: float) -> ProgressEstimate:
        assert self._ref_map is not None
        alignment = self._last_alignment

        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)

        if self._last_progress_at_sec > 0.0 and now_sec >= self._last_progress_at_sec:
            last_progress_age = now_sec - self._last_progress_at_sec
        else:
            last_progress_age = 9999.0

        recently_progressed = last_progress_age <= self.recent_progress_sec

        active_speaking = False
        if alignment is not None:
            forward_delta = alignment.candidate_ref_idx - estimated_idx
            event_fresh = (
                (now_sec - self._last_event_at_sec) <= self.speaking_event_fresh_sec
                if self._last_event_at_sec > 0.0 and now_sec >= self._last_event_at_sec
                else False
            )

            if recently_progressed:
                active_speaking = True
            elif (
                event_fresh
                and alignment.stable
                and alignment.confidence >= self.active_speaking_confidence
                and forward_delta >= 0
            ):
                active_speaking = True
            elif (
                event_fresh
                and alignment.confidence >= max(self.active_speaking_confidence, 0.76)
                and alignment.local_match_ratio >= self.local_match_for_speaking
                and alignment.candidate_ref_idx > alignment.committed_ref_idx
            ):
                active_speaking = True

        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            source_candidate_ref_idx=(
                int(alignment.candidate_ref_idx) if alignment is not None else int(self._last_source_candidate_idx)
            ),
            source_committed_ref_idx=(
                int(alignment.committed_ref_idx) if alignment is not None else estimated_idx
            ),
            confidence=float(alignment.confidence) if alignment is not None else 0.0,
            stable=bool(alignment.stable) if alignment is not None else False,
            event_emitted_at_sec=float(self._last_event_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_velocity_idx_per_sec=float(self._last_velocity),
            recently_progressed=recently_progressed,
            last_progress_age_sec=float(last_progress_age),
            active_speaking=active_speaking,
            phase_hint="follow" if active_speaking or recently_progressed else "wait",
        )