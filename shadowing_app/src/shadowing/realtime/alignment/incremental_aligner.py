from __future__ import annotations

from pypinyin import lazy_pinyin

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AlignResult, AsrEvent, ReferenceMap
from shadowing.realtime.alignment.scoring import AlignmentScorer
from shadowing.realtime.alignment.window_selector import WindowSelector


class IncrementalAligner(Aligner):
    def __init__(
        self,
        stable_needed: int = 2,
        min_confidence: float = 0.45,
        max_hyp_tokens: int = 8,
    ) -> None:
        self.ref_map: ReferenceMap | None = None
        self.committed_idx: int = 0

        self.last_candidate_idx: int = 0
        self.stable_count: int = 0

        self.stable_needed = stable_needed
        self.min_confidence = min_confidence
        self.max_hyp_tokens = max_hyp_tokens

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

        hyp_chars = list(event.normalized_text.strip())
        hyp_pys = event.pinyin_seq

        if not hyp_chars or not hyp_pys:
            return None

        hyp_chars = hyp_chars[-self.max_hyp_tokens :]
        hyp_pys = hyp_pys[-self.max_hyp_tokens :]

        window, start, _ = self.window_selector.select(self.ref_map, self.committed_idx)
        if not window:
            return None

        candidate_idx, confidence = self._best_alignment(window, start, hyp_chars, hyp_pys)

        if candidate_idx < self.committed_idx:
            candidate_idx = self.committed_idx
            confidence *= 0.7

        if candidate_idx == self.last_candidate_idx:
            self.stable_count += 1
        else:
            self.last_candidate_idx = candidate_idx
            self.stable_count = 1

        stable = self.stable_count >= self.stable_needed and confidence >= self.min_confidence
        if stable and candidate_idx > self.committed_idx:
            self.committed_idx = candidate_idx

        token = self.ref_map.tokens[self.committed_idx]
        return AlignResult(
            committed_ref_idx=self.committed_idx,
            candidate_ref_idx=candidate_idx,
            ref_time_sec=token.t_end,
            confidence=confidence,
            stable=stable,
            matched_text="".join(hyp_chars),
            matched_pinyin=hyp_pys,
        )

    def _best_alignment(
        self,
        window,
        window_start_idx: int,
        hyp_chars: list[str],
        hyp_pys: list[str],
    ) -> tuple[int, float]:
        """
        简化版局部 DP：
        - ref 维度：window
        - hyp 维度：最近若干 token
        - 目标：找最佳末端落点
        """
        n = len(window)
        m = min(len(hyp_chars), len(hyp_pys))

        if n == 0 or m == 0:
            return self.committed_idx, 0.0

        dp = [[0.0 for _ in range(m + 1)] for _ in range(n + 1)]

        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + self.scorer.deletion_penalty()

        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + self.scorer.insertion_penalty()

        best_score = float("-inf")
        best_i = 0

        for i in range(1, n + 1):
            ref_tok = window[i - 1]
            for j in range(1, m + 1):
                match_score = self.scorer.score_token_pair(
                    ref_char=ref_tok.char,
                    ref_py=ref_tok.pinyin,
                    hyp_char=hyp_chars[j - 1],
                    hyp_py=hyp_pys[j - 1],
                )

                score_match = dp[i - 1][j - 1] + match_score
                score_del = dp[i - 1][j] + self.scorer.deletion_penalty()
                score_ins = dp[i][j - 1] + self.scorer.insertion_penalty()

                dp[i][j] = max(score_match, score_del, score_ins)

            if dp[i][m] > best_score:
                best_score = dp[i][m]
                best_i = i

        candidate_idx = window_start_idx + best_i - 1
        candidate_idx = max(0, candidate_idx)

        norm = max(1.0, m * 3.0)
        confidence = max(0.0, min(1.0, (best_score + norm) / (2.0 * norm)))

        return candidate_idx, confidence