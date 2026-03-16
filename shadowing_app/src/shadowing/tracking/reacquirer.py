from __future__ import annotations
from shadowing.types import ReferenceMap, TrackingMode, TrackingSnapshot


class Reacquirer:
    def __init__(self, max_anchor_jump: int = 24, min_anchor_score: float = 0.52) -> None:
        self.max_anchor_jump = int(max_anchor_jump)
        self.min_anchor_score = float(min_anchor_score)

    def maybe_reanchor(self, *, snapshot: TrackingSnapshot, anchor_manager, ref_map: ReferenceMap) -> TrackingSnapshot:
        _ = ref_map
        anchor = anchor_manager.strong_anchor() or anchor_manager.weak_anchor()
        if anchor is None:
            return snapshot
        if snapshot.tracking_mode not in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            return snapshot
        if snapshot.tracking_quality.anchor_score < self.min_anchor_score:
            return snapshot
        anchor_idx = int(anchor.ref_idx)
        cur_idx = int(snapshot.candidate_ref_idx)
        if abs(cur_idx - anchor_idx) > self.max_anchor_jump:
            return snapshot
        if snapshot.anchor_consistency < self.min_anchor_score:
            return snapshot
        return TrackingSnapshot(
            candidate_ref_idx=max(cur_idx, anchor_idx),
            committed_ref_idx=max(int(snapshot.committed_ref_idx), anchor_idx),
            candidate_ref_time_sec=float(snapshot.candidate_ref_time_sec),
            confidence=float(max(snapshot.confidence, min(0.88, anchor.quality_score))),
            stable=bool(snapshot.stable),
            local_match_ratio=float(snapshot.local_match_ratio),
            repeat_penalty=float(snapshot.repeat_penalty),
            monotonic_consistency=float(snapshot.monotonic_consistency),
            anchor_consistency=float(max(snapshot.anchor_consistency, 0.72)),
            emitted_at_sec=float(snapshot.emitted_at_sec),
            tracking_mode=TrackingMode.REACQUIRING,
            tracking_quality=snapshot.tracking_quality,
            matched_text=snapshot.matched_text,
        )
