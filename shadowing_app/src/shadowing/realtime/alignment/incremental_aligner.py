from __future__ import annotations

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AlignResult, AsrEvent, ReferenceMap
from shadowing.realtime.alignment.window_selector import WindowSelector


class IncrementalAligner(Aligner):
    def __init__(
        self,
        stable_needed: int = 2,
        min_confidence: float = 0.45,
        max_hyp_tokens: int = 12,
    ) -> None:
        self.ref_map: ReferenceMap | None = None
        self.committed_idx: int = 0

        self.last_candidate_idx: int = 0
        self.stable_count: int = 0

        self.stable_needed = stable_needed
        self.min_confidence = min_confidence
        self.max_hyp_tokens = max_hyp_tokens

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

        # 当前 fake 调试阶段：始终使用“前缀增长”视角
        hyp_chars = hyp_chars[: self.max_hyp_tokens]
        hyp_pys = hyp_pys[: self.max_hyp_tokens]

        window, start, _ = self.window_selector.select(self.ref_map, self.committed_idx)
        if not window:
            return None

        # 关键补丁：
        # window 不一定从 0 开始，hyp 也必须裁掉相同数量的前缀，
        # 否则 window 开头和 hyp 开头会错位。
        if start > 0:
            offset = min(start, len(hyp_chars), len(hyp_pys))
            hyp_chars = hyp_chars[offset:]
            hyp_pys = hyp_pys[offset:]

        # 如果裁完空了，安全返回当前 committed 状态
        if not hyp_chars or not hyp_pys:
            token = self.ref_map.tokens[self.committed_idx]
            return AlignResult(
                committed_ref_idx=self.committed_idx,
                candidate_ref_idx=self.committed_idx,
                ref_time_sec=token.t_end,
                confidence=0.0,
                stable=False,
                matched_text="",
                matched_pinyin=[],
            )

        candidate_idx, confidence = self._best_prefix_alignment(window, start, hyp_chars, hyp_pys)

        # 不允许明显回退
        if candidate_idx < self.committed_idx:
            candidate_idx = self.committed_idx
            confidence *= 0.8

        # 关键补丁：
        # candidate 单调前进也算稳定推进，不必要求“完全相同重复出现”
        if confidence >= self.min_confidence:
            if candidate_idx > self.last_candidate_idx:
                self.stable_count += 1
            elif candidate_idx == self.last_candidate_idx:
                self.stable_count += 1
            else:
                self.stable_count = 1
        else:
            self.stable_count = 0

        self.last_candidate_idx = candidate_idx

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

    def _best_prefix_alignment(
        self,
        window,
        window_start_idx: int,
        hyp_chars: list[str],
        hyp_pys: list[str],
    ) -> tuple[int, float]:
        """
        用前向扫描做轻量前缀对齐：
        - 逐个尝试窗口前缀长度 i
        - 比较 reference[:i] 和 hyp[:k]
        - 选分数最高的落点

        适合：
        - 已知文本
        - fake 前缀增长 partial
        - 先把 committed 推起来
        """
        best_score = -1.0
        best_i = 1

        max_ref_len = len(window)
        hyp_len = min(len(hyp_chars), len(hyp_pys))

        for i in range(1, max_ref_len + 1):
            ref_slice = window[:i]

            cmp_len = min(i, hyp_len)
            if cmp_len == 0:
                continue

            score = 0.0
            for j in range(cmp_len):
                ref_tok = ref_slice[j]
                hyp_char = hyp_chars[j]
                hyp_py = hyp_pys[j]

                if ref_tok.char == hyp_char:
                    score += 1.0
                elif ref_tok.pinyin == hyp_py:
                    score += 0.8
                else:
                    score += 0.0

            # 归一化到 0~1
            score = score / cmp_len

            # 略偏好更长但仍高分的匹配
            score += min(i, hyp_len) * 0.01

            if score > best_score:
                best_score = score
                best_i = i

        candidate_idx = window_start_idx + best_i - 1
        candidate_idx = max(0, candidate_idx)

        confidence = max(0.0, min(1.0, best_score))
        return candidate_idx, confidence