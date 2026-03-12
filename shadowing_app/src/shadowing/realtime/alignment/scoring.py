from __future__ import annotations

from rapidfuzz import fuzz


class AlignmentScorer:
    """
    简化版 token 打分：
    - 字符精确匹配最高
    - 拼音精确匹配次之
    - 近似拼音再降一级
    """

    def score_token_pair(
        self,
        ref_char: str,
        ref_py: str,
        hyp_char: str,
        hyp_py: str,
    ) -> float:
        if ref_char == hyp_char:
            return 3.0

        if ref_py == hyp_py:
            return 2.0

        py_sim = fuzz.ratio(ref_py, hyp_py)
        if py_sim >= 80:
            return 1.0

        return -1.5

    def insertion_penalty(self) -> float:
        return -0.7

    def deletion_penalty(self) -> float:
        return -0.9

    def backward_penalty(self) -> float:
        return -2.0