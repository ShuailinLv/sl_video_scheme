from __future__ import annotations

from rapidfuzz import fuzz


class AlignmentScorer:
    def score_token_pair(self, ref_char: str, ref_py: str, hyp_char: str, hyp_py: str) -> float:
        if ref_char == hyp_char:
            return 3.0
        if ref_py and ref_py == hyp_py:
            return 2.0
        py_sim = fuzz.ratio(ref_py, hyp_py) if ref_py and hyp_py else 0.0
        if py_sim >= 80:
            return 1.0
        return -1.5

    def insertion_penalty(self) -> float:
        return -0.7

    def deletion_penalty(self) -> float:
        return -0.9

    def backward_penalty(self) -> float:
        return -2.0