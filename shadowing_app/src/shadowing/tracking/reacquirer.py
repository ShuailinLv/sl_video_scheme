from __future__ import annotations

from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.types import TrackingMode, TrackingSnapshot


class Reacquirer:
    def __init__(
        self,
        max_reanchor_distance: int = 18,
        min_quality_for_reanchor: float = 0.66,
    ) -> None:
        self.max_reanchor_distance = int(max_reanchor_distance)
        self.min_quality_for_reanchor = float(min_quality_for_reanchor)

    def maybe_reanchor(
        self,
        snapshot: TrackingSnapshot,
        anchor_manager: AnchorManager,
    ) -> TrackingSnapshot:
        if snapshot.tracking_mode not in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            return snapshot

        strong = anchor_manager.strong_anchor()
        weak = anchor_manager.weak_anchor()
        anchor = strong if strong is not None else weak
        if anchor is None:
            return snapshot

        if snapshot.tracking_quality.overall_score < self.min_quality_for_reanchor:
            return snapshot

        if abs(snapshot.candidate_ref_idx - anchor.ref_idx) > self.max_reanchor_distance:
            return snapshot

        repaired_mode = TrackingMode.WEAK_LOCKED
        repaired_quality = snapshot.tracking_quality
        repaired_quality.mode = repaired_mode
        repaired_quality.is_reliable = repaired_quality.overall_score >= 0.60

        return TrackingSnapshot(
            candidate_ref_idx=int(snapshot.candidate_ref_idx),
            committed_ref_idx=max(int(snapshot.committed_ref_idx), int(anchor.ref_idx)),
            candidate_ref_time_sec=float(snapshot.candidate_ref_time_sec),
            confidence=float(snapshot.confidence),
            stable=bool(snapshot.stable),
            local_match_ratio=float(snapshot.local_match_ratio),
            repeat_penalty=float(snapshot.repeat_penalty),
            monotonic_consistency=float(snapshot.monotonic_consistency),
            anchor_consistency=float(snapshot.anchor_consistency),
            emitted_at_sec=float(snapshot.emitted_at_sec),
            tracking_mode=repaired_mode,
            tracking_quality=repaired_quality,
            matched_text=snapshot.matched_text,
        )