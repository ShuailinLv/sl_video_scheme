from __future__ import annotations

from dataclasses import dataclass

from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.tracking.loss_detector import LossDetector
from shadowing.tracking.reacquirer import Reacquirer
from shadowing.types import AsrEvent, ReferenceMap, TrackingMode, TrackingQuality, TrackingSnapshot


@dataclass(slots=True)
class _TrackingContext:
    ref_map: ReferenceMap | None = None
    last_generation: int = 0


class TrackingEngine:
    def __init__(self, aligner: IncrementalAligner, debug: bool = False) -> None:
        self.aligner = aligner
        self.debug = bool(debug)
        self.anchor_manager = AnchorManager()
        self.loss_detector = LossDetector()
        self.reacquirer = Reacquirer()
        self._ctx = _TrackingContext()

    def reset(self, ref_map: ReferenceMap) -> None:
        self._ctx = _TrackingContext(ref_map=ref_map, last_generation=0)
        reference_text = "".join(token.char for token in ref_map.tokens)
        self.aligner.set_reference(reference_text)
        self.anchor_manager.reset()
        self.loss_detector.reset()

    def on_playback_generation_changed(self, generation: int) -> None:
        self._ctx.last_generation = int(generation)
        committed = self.aligner.get_committed_index()
        self.aligner.reset(committed=committed)

    def recenter_from_audio(
        self,
        *,
        ref_idx_hint: int,
        search_back: int = 12,
        search_ahead: int = 28,
        budget_events: int = 6,
    ) -> None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return
        hint = max(0, min(int(ref_idx_hint), len(ref_map.tokens) - 1))
        self.aligner.force_recenter(
            committed_hint=hint,
            window_back=int(search_back),
            window_ahead=int(search_ahead),
            budget_events=int(budget_events),
        )

    def update(self, event: AsrEvent) -> TrackingSnapshot | None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return None

        result = self.aligner.update(event.normalized_text)
        max_idx = len(ref_map.tokens) - 1
        candidate_idx = max(0, min(int(result.candidate), max_idx))
        committed_idx = max(0, min(int(result.committed), max_idx))

        observation_score = float(max(0.0, min(1.0, result.conf)))
        local_match = float(max(0.0, min(1.0, result.local_match)))
        monotonic_consistency = 1.0 if not result.backward else 0.0
        repeat_penalty = 0.12 if result.repeated_candidate else 0.0
        anchor_score = float(self.anchor_manager.anchor_consistency(candidate_idx))

        preliminary_overall = (
            0.60 * observation_score
            + 0.25 * local_match
            + 0.15 * monotonic_consistency
        )
        preliminary_reliable = bool(
            observation_score >= 0.60
            and local_match >= 0.58
            and not result.backward
        )

        provisional = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=TrackingMode.BOOTSTRAP,
            tracking_quality=TrackingQuality(
                overall_score=float(preliminary_overall),
                observation_score=float(observation_score),
                temporal_consistency_score=0.72,
                anchor_score=float(anchor_score),
                mode=TrackingMode.BOOTSTRAP,
                is_reliable=preliminary_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )

        mode, temporal_consistency = self.loss_detector.update(
            provisional,
            overall_score=preliminary_overall,
            is_reliable=preliminary_reliable,
        )

        overall_score = (
            0.50 * observation_score
            + 0.20 * local_match
            + 0.15 * float(temporal_consistency)
            + 0.15 * anchor_score
        )
        overall_score = float(max(0.0, min(1.0, overall_score)))
        is_reliable = bool(
            overall_score >= 0.60
            and observation_score >= 0.58
            and local_match >= 0.55
            and not result.backward
        )

        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=mode,
            tracking_quality=TrackingQuality(
                overall_score=overall_score,
                observation_score=float(observation_score),
                temporal_consistency_score=float(temporal_consistency),
                anchor_score=float(anchor_score),
                mode=mode,
                is_reliable=is_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )

        self.anchor_manager.update(snapshot)
        snapshot = self.reacquirer.maybe_reanchor(
            snapshot=snapshot,
            anchor_manager=self.anchor_manager,
            ref_map=ref_map,
        )
        return snapshot