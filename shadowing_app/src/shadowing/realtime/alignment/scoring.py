from __future__ import annotations


class AlignmentScorer:
    """
    字符精确匹配 > 拼音精确匹配 > 近音匹配
    插入/删除/回退给惩罚
    """

    def score_token_pair(
        self,
        ref_char: str,
        ref_py: str,
        hyp_char: str,
        hyp_py: str,
    ) -> float:
        if ref_char == hyp_char:
            return 2.0
        if ref_py == hyp_py:
            return 1.2
        return -0.8