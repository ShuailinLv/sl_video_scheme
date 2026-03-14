from __future__ import annotations

from shadowing.interfaces.aligner import Aligner
from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.tracking.loss_detector import LossDetector
from shadowing.tracking.reacquirer import Reacquirer
from shadowing.types import ReferenceMap, AsrEvent, TrackingMode, TrackingQuality, TrackingSnapshot


class TrackingEngine:
    def __init__(self, aligner: Aligner, debug: bool = False) -> None:
        self.aligner = aligner
        self.debug = bool(debug)

        self.ref_map: ReferenceMap | None = None
        self.anchor_manager = AnchorManager()
        self.loss_detector = LossDetector()
        self.reacquirer = Reacquirer()

        self._last_candidate_idx = 0
        self._last_snapshot: TrackingSnapshot | None = None

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self._last_candidate_idx = 0
        self._last_snapshot = None
        self.anchor_manager.reset()
        self.loss_detector.reset()
        self.aligner.reset(reference_map)

    def on_playback_generation_changed(self, generation: int) -> None:
        self.aligner.on_playback_generation_changed(generation)
        self.loss_detector.reset()

    def update(self, event: AsrEvent) -> TrackingSnapshot | None:
        if self.ref_map is None:
            return None

        alignment = self.aligner.update(event)
        if alignment is None:
            return self._last_snapshot

        candidate_idx = int(alignment.candidate_ref_idx)
        committed_idx = int(alignment.committed_ref_idx)

        monotonic_consistency = self._compute_monotonic_consistency(candidate_idx)
        anchor_consistency = self.anchor_manager.anchor_consistency(candidate_idx)

        observation_score = (
            0.58 * alignment.confidence
            + 0.24 * alignment.local_match_ratio
            + 0.12 * (1.0 - alignment.repeat_penalty)
            + 0.06 * (1.0 if alignment.stable else 0.0)
        )
        observation_score = max(0.0, min(1.0, observation_score))

        seed_quality = (
            0.62 * observation_score
            + 0.22 * anchor_consistency
            + 0.16 * monotonic_consistency
        )
        seed_quality = max(0.0, min(1.0, seed_quality))
        is_reliable = seed_quality >= 0.66 and alignment.confidence >= 0.62

        provisional_quality = TrackingQuality(
            overall_score=float(seed_quality),
            observation_score=float(observation_score),
            temporal_consistency_score=0.72,
            anchor_score=float(anchor_consistency),
            mode=TrackingMode.BOOTSTRAP,
            is_reliable=bool(is_reliable),
        )

        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(alignment.ref_time_sec),
            confidence=float(alignment.confidence),
            stable=bool(alignment.stable),
            local_match_ratio=float(alignment.local_match_ratio),
            repeat_penalty=float(alignment.repeat_penalty),
            monotonic_consistency=float(monotonic_consistency),
            anchor_consistency=float(anchor_consistency),
            emitted_at_sec=float(alignment.emitted_at_sec),
            tracking_mode=TrackingMode.BOOTSTRAP,
            tracking_quality=provisional_quality,
            matched_text=alignment.matched_text,
        )

        mode, temporal_consistency = self.loss_detector.update(
            snapshot=snapshot,
            overall_score=seed_quality,
            is_reliable=is_reliable,
        )

        overall_score = (
            0.48 * observation_score
            + 0.22 * temporal_consistency
            + 0.18 * anchor_consistency
            + 0.12 * monotonic_consistency
        )
        overall_score = max(0.0, min(1.0, overall_score))

        quality = TrackingQuality(
            overall_score=float(overall_score),
            observation_score=float(observation_score),
            temporal_consistency_score=float(temporal_consistency),
            anchor_score=float(anchor_consistency),
            mode=mode,
            is_reliable=bool(overall_score >= 0.66 and alignment.confidence >= 0.62),
        )

        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(alignment.ref_time_sec),
            confidence=float(alignment.confidence),
            stable=bool(alignment.stable),
            local_match_ratio=float(alignment.local_match_ratio),
            repeat_penalty=float(alignment.repeat_penalty),
            monotonic_consistency=float(monotonic_consistency),
            anchor_consistency=float(anchor_consistency),
            emitted_at_sec=float(alignment.emitted_at_sec),
            tracking_mode=mode,
            tracking_quality=quality,
            matched_text=alignment.matched_text,
        )

        snapshot = self.reacquirer.maybe_reanchor(snapshot, self.anchor_manager)
        self.anchor_manager.update(snapshot)

        self._last_candidate_idx = candidate_idx
        self._last_snapshot = snapshot

        if self.debug:
            print(
                "[TRACK] "
                f"mode={snapshot.tracking_mode.value} "
                f"cand={snapshot.candidate_ref_idx} "
                f"committed={snapshot.committed_ref_idx} "
                f"overall={snapshot.tracking_quality.overall_score:.3f} "
                f"obs={snapshot.tracking_quality.observation_score:.3f} "
                f"temp={snapshot.tracking_quality.temporal_consistency_score:.3f} "
                f"anchor={snapshot.tracking_quality.anchor_score:.3f}"
            )

        return snapshot

    def snapshot(self) -> TrackingSnapshot | None:
        return self._last_snapshot

    def _compute_monotonic_consistency(self, candidate_idx: int) -> float:
        delta = candidate_idx - self._last_candidate_idx
        if delta >= 0:
            return 1.0
        return max(0.0, 1.0 - min(1.0, abs(delta) / 8.0))