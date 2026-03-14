from __future__ import annotations

from dataclasses import dataclass
from math import exp

from shadowing.interfaces.aligner import Aligner
from shadowing.realtime.alignment.scoring import AlignmentScorer
from shadowing.realtime.alignment.window_selector import WindowSelector
from shadowing.types import (
    AlignResult,
    AsrEvent,
    AsrEventType,
    CandidateAlignment,
    HypToken,
    ReferenceMap,
)


@dataclass(slots=True)
class _RefTokenView:
    idx: int
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int


@dataclass(slots=True)
class _CommitState:
    committed_idx: int = 0
    stable_run: int = 0
    backward_run: int = 0
    last_candidate_idx: int = 0
    generation: int = 0
    recovering_after_seek: bool = False


class IncrementalAligner(Aligner):
    def __init__(
        self,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_frames: int = 2,
        min_confidence: float = 0.60,
        backward_lock_frames: int = 3,
        clause_boundary_bonus: float = 0.15,
        cross_clause_backward_extra_penalty: float = 0.20,
        debug: bool = False,
    ) -> None:
        self.window_selector = WindowSelector(look_back=window_back, look_ahead=window_ahead)
        self.scorer = AlignmentScorer()
        self.stable_frames = int(stable_frames)
        self.min_confidence = float(min_confidence)
        self.backward_lock_frames = int(backward_lock_frames)
        self.clause_boundary_bonus = float(clause_boundary_bonus)
        self.cross_clause_backward_extra_penalty = float(cross_clause_backward_extra_penalty)
        self.debug = bool(debug)

        self.ref_map: ReferenceMap | None = None
        self.ref_tokens: list[_RefTokenView] = []
        self.state = _CommitState()

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self.ref_tokens = [
            _RefTokenView(
                idx=t.idx,
                char=t.char,
                pinyin=t.pinyin,
                t_start=t.t_start,
                t_end=t.t_end,
                sentence_id=t.sentence_id,
                clause_id=t.clause_id,
            )
            for t in reference_map.tokens
        ]
        self.state = _CommitState()

    def on_playback_generation_changed(self, generation: int) -> None:
        self.state.generation = int(generation)
        self.state.stable_run = 0
        self.state.backward_run = 0
        self.state.last_candidate_idx = self.state.committed_idx
        self.state.recovering_after_seek = True

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None or not self.ref_tokens:
            return None

        if event.event_type not in (AsrEventType.PARTIAL, AsrEventType.FINAL):
            return None

        if len(event.chars) != len(event.pinyin_seq):
            min_len = min(len(event.chars), len(event.pinyin_seq))
            chars = event.chars[:min_len]
            pinyin_seq = event.pinyin_seq[:min_len]
        else:
            chars = event.chars
            pinyin_seq = event.pinyin_seq

        if not chars:
            return None

        hyp_tokens = [HypToken(char=c, pinyin=py) for c, py in zip(chars, pinyin_seq, strict=True)]
        window_tokens, window_start, window_end = self.window_selector.select(
            self.ref_map, self.state.committed_idx
        )
        candidate = self._align_window(
            hyp_tokens=hyp_tokens,
            ref_tokens=window_tokens,
            ref_offset=window_start,
        )
        stable = self._observe_candidate(candidate, event.event_type)

        ref_time = self.ref_tokens[candidate.ref_end_idx].t_start
        matched_text = "".join(
            self.ref_tokens[i].char
            for i in candidate.matched_ref_indices
            if 0 <= i < len(self.ref_tokens)
        )
        matched_pinyin = [
            self.ref_tokens[i].pinyin
            for i in candidate.matched_ref_indices
            if 0 <= i < len(self.ref_tokens)
        ]

        if self.debug:
            print(
                "[ALIGN] "
                f"committed={self.state.committed_idx} "
                f"candidate={candidate.ref_end_idx} "
                f"score={candidate.score:.3f} "
                f"conf={candidate.confidence:.3f} "
                f"stable={stable} "
                f"backward={candidate.backward_jump} "
                f"matched_n={len(candidate.matched_ref_indices)} "
                f"hyp_n={len(hyp_tokens)} "
                f"mode={candidate.mode}"
            )

        return AlignResult(
            committed_ref_idx=self.state.committed_idx,
            candidate_ref_idx=candidate.ref_end_idx,
            ref_time_sec=ref_time,
            confidence=candidate.confidence,
            stable=stable,
            matched_text=matched_text,
            matched_pinyin=matched_pinyin,
            window_start_idx=window_start,
            window_end_idx=max(window_start, window_end - 1),
            alignment_mode=candidate.mode,
            backward_jump_detected=candidate.backward_jump,
            debug_score=candidate.score,
            debug_stable_run=self.state.stable_run,
            debug_backward_run=self.state.backward_run,
            debug_matched_count=len(candidate.matched_ref_indices),
            debug_hyp_length=len(hyp_tokens),
        )

    def _observe_candidate(self, candidate: CandidateAlignment, event_type: AsrEventType) -> bool:
        stable = False

        if self.state.recovering_after_seek:
            if not candidate.backward_jump and candidate.confidence >= self.min_confidence:
                self.state.recovering_after_seek = False
            else:
                return False

        if candidate.backward_jump:
            self.state.backward_run += 1
        else:
            self.state.backward_run = 0

        if candidate.ref_end_idx == self.state.last_candidate_idx:
            self.state.stable_run += 1
        else:
            self.state.stable_run = 1

        self.state.last_candidate_idx = candidate.ref_end_idx

        if event_type == AsrEventType.FINAL:
            if candidate.backward_jump:
                if candidate.confidence >= 0.90 and self.state.backward_run >= self.backward_lock_frames:
                    self.state.committed_idx = candidate.ref_end_idx
                    self.state.stable_run = 0
                    self.state.backward_run = 0
                    return True
                return False

            if candidate.confidence >= self.min_confidence and candidate.ref_end_idx >= self.state.committed_idx:
                self.state.committed_idx = candidate.ref_end_idx
                self.state.stable_run = 0
                self.state.backward_run = 0
                return True
            return False

        if candidate.backward_jump:
            if candidate.confidence >= 0.90 and self.state.backward_run >= self.backward_lock_frames:
                self.state.committed_idx = candidate.ref_end_idx
                stable = True
            return stable

        if candidate.confidence < self.min_confidence:
            return False

        if candidate.ref_end_idx < self.state.committed_idx:
            return False

        if self.state.stable_run >= self.stable_frames:
            self.state.committed_idx = candidate.ref_end_idx
            stable = True

        return stable

    def _align_window(
        self,
        hyp_tokens: list[HypToken],
        ref_tokens: list[_RefTokenView],
        ref_offset: int,
    ) -> CandidateAlignment:
        m = len(hyp_tokens)
        n = len(ref_tokens)

        if m == 0 or n == 0:
            committed = self.state.committed_idx
            return CandidateAlignment(
                ref_start_idx=committed,
                ref_end_idx=committed,
                score=0.0,
                confidence=0.0,
            )

        dp = [[0.0] * (n + 1) for _ in range(m + 1)]
        trace = [["S"] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            dp[i][0] = dp[i - 1][0] + self.scorer.insertion_penalty()
            trace[i][0] = "I"

        current_clause = (
            self.ref_tokens[min(self.state.committed_idx, len(self.ref_tokens) - 1)].clause_id
            if self.ref_tokens
            else 0
        )

        for j in range(1, n + 1):
            penalty = self.scorer.deletion_penalty()
            global_idx = ref_offset + (j - 1)

            if global_idx < self.state.committed_idx:
                penalty += self.scorer.backward_penalty()
                if self.ref_tokens[global_idx].clause_id != current_clause:
                    penalty -= self.cross_clause_backward_extra_penalty

            dp[0][j] = dp[0][j - 1] + penalty
            trace[0][j] = "D"

        best_j = 1
        best_score = float("-inf")

        for i in range(1, m + 1):
            hyp = hyp_tokens[i - 1]
            for j in range(1, n + 1):
                ref = ref_tokens[j - 1]

                match_score = self.scorer.score_token_pair(ref.char, ref.pinyin, hyp.char, hyp.pinyin)
                if ref.idx == self.state.committed_idx + 1:
                    match_score += self.clause_boundary_bonus * 0.25

                diag = dp[i - 1][j - 1] + match_score
                ins = dp[i - 1][j] + self.scorer.insertion_penalty()

                delete_penalty = self.scorer.deletion_penalty()
                if ref.idx < self.state.committed_idx:
                    delete_penalty += self.scorer.backward_penalty()
                    if ref.clause_id != current_clause:
                        delete_penalty -= self.cross_clause_backward_extra_penalty

                dele = dp[i][j - 1] + delete_penalty

                best = max(diag, ins, dele)
                dp[i][j] = best
                trace[i][j] = "M" if best == diag else ("I" if best == ins else "D")

                if i == m and best > best_score:
                    best_score = best
                    best_j = j

        matched_indices: list[int] = []
        i = m
        j = best_j
        while i > 0 and j > 0:
            op = trace[i][j]
            if op == "M":
                matched_indices.append(ref_offset + j - 1)
                i -= 1
                j -= 1
            elif op == "I":
                i -= 1
            else:
                j -= 1

        matched_indices.reverse()

        ref_end_idx = ref_offset + best_j - 1
        ref_end_idx = max(0, min(ref_end_idx, len(self.ref_tokens) - 1))
        ref_start_idx = matched_indices[0] if matched_indices else max(ref_offset, ref_end_idx)
        backward_jump = ref_end_idx < self.state.committed_idx
        norm_score = best_score / max(1, len(hyp_tokens))
        confidence = 1.0 / (1.0 + exp(-1.25 * norm_score))
        mode = "backward" if backward_jump else "normal"

        return CandidateAlignment(
            ref_start_idx=ref_start_idx,
            ref_end_idx=ref_end_idx,
            score=best_score,
            confidence=max(0.0, min(1.0, confidence)),
            matched_ref_indices=matched_indices,
            backward_jump=backward_jump,
            mode=mode,
        )