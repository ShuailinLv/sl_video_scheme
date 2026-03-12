from __future__ import annotations

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AlignResult, AsrEvent, ReferenceMap
from shadowing.realtime.alignment.scoring import AlignmentScorer
from shadowing.realtime.alignment.window_selector import WindowSelector


class IncrementalAligner(Aligner):
    def __init__(self) -> None:
        self.ref_map: ReferenceMap | None = None
        self.committed_idx: int = 0
        self.last_candidate_idx: int = 0
        self.stable_count: int = 0
        self.scorer = AlignmentScorer()
        self.window_selector = WindowSelector()

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self.committed_idx = 0
        self.last_candidate_idx = 0
        self.stable_count = 0

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None:
            return None

        if not event.normalized_text:
            return None

        window, start, _ = self.window_selector.select(self.ref_map, self.committed_idx)

        # TODO:
        # 1. 将用户文本切成 token
        # 2. 在 window 上做增量加权对齐
        # 3. 产出 candidate_idx
        candidate_idx = min(start + len(event.pinyin_seq), len(self.ref_map.tokens) - 1)

        if candidate_idx == self.last_candidate_idx:
            self.stable_count += 1
        else:
            self.stable_count = 1
            self.last_candidate_idx = candidate_idx

        stable = self.stable_count >= 2
        if stable and candidate_idx > self.committed_idx:
            self.committed_idx = candidate_idx

        token = self.ref_map.tokens[self.committed_idx]
        return AlignResult(
            committed_ref_idx=self.committed_idx,
            candidate_ref_idx=candidate_idx,
            ref_time_sec=token.t_end,
            confidence=0.75,
            stable=stable,
            matched_text=event.normalized_text,
            matched_pinyin=event.pinyin_seq,
        )