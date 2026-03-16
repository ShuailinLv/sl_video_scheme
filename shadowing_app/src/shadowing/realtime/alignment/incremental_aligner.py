from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+", "", text)
    return text


def _safe_ratio(a: int, b: int) -> float:
    if b <= 0:
        return 0.0
    return max(0.0, min(1.0, float(a) / float(b)))


@dataclass(slots=True)
class AlignmentResult:
    committed: int
    candidate: int
    score: float
    conf: float
    stable: bool
    backward: bool
    matched_n: int
    hyp_n: int
    mode: str
    window: tuple[int, int]
    local_match: float = 0.0
    soft_committed: bool = False
    accepted: bool = False
    raw_text: str = ""
    normalized_text: str = ""
    repeated_candidate: bool = False
    weak_forward: bool = False

    @property
    def advance(self) -> int:
        return max(0, self.candidate - self.committed)


class IncrementalAligner:
    """
    改进点：
    1. 不再主要依赖 LCP 前缀命中，而是用“局部子串编辑相似度 + 前后缀锚点 + ngram 重叠”综合评分。
    2. 对 partial 回改、插字漏字、长 partial 漂移更稳。
    3. 通过 recovery 模式自动放宽搜索窗，参数明显减少。
    """

    def __init__(
        self,
        reference_text: str | Sequence[str] | None = None,
        *,
        window_back: int = 10,
        window_ahead: int = 48,
        stable_hits: int = 2,
        min_confidence: float = 0.62,
        debug: bool = False,
    ) -> None:
        self.window_back = int(window_back)
        self.window_ahead = int(window_ahead)
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = float(min_confidence)
        self.debug = bool(debug)

        self.reference_text = ""
        self.reference_norm = ""

        self._committed = 0
        self._last_candidate = 0
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = 0

        self._forced_center: int | None = None
        self._forced_budget = 0
        self._forced_window_back: int | None = None
        self._forced_window_ahead: int | None = None

        if reference_text is not None:
            self.set_reference(reference_text)

    @property
    def committed_index(self) -> int:
        return self._committed

    def get_committed_index(self) -> int:
        return self._committed

    def set_reference(self, reference_text: str | Sequence[str]) -> None:
        if isinstance(reference_text, (list, tuple)):
            reference_text = "".join(str(x) for x in reference_text)
        self.reference_text = reference_text or ""
        self.reference_norm = _normalize_text(self.reference_text)
        self.reset(committed=0)

    def reset(self, committed: int | None = None) -> None:
        if committed is None:
            self._committed = 0
        else:
            self._committed = max(0, min(int(committed), len(self.reference_norm)))
        self._last_candidate = self._committed
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = (self._committed // 4) * 4
        self._forced_center = None
        self._forced_budget = 0
        self._forced_window_back = None
        self._forced_window_ahead = None

    def force_recenter(
        self,
        committed_hint: int,
        *,
        window_back: int | None = None,
        window_ahead: int | None = None,
        budget_events: int = 6,
    ) -> None:
        if not self.reference_norm:
            return
        hint = max(0, min(int(committed_hint), len(self.reference_norm)))
        self._forced_center = hint
        self._forced_window_back = int(window_back) if window_back is not None else max(16, self.window_back + 6)
        self._forced_window_ahead = int(window_ahead) if window_ahead is not None else max(32, self.window_ahead // 2)
        self._forced_budget = max(1, int(budget_events))
        self._committed = min(self._committed, hint)

    def update(self, hypothesis_text: str) -> AlignmentResult:
        return self.align(hypothesis_text)

    def align(self, hypothesis_text: str) -> AlignmentResult:
        hyp_raw = hypothesis_text or ""
        hyp = _normalize_text(hyp_raw)

        if not self.reference_norm:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=len(hyp),
                mode="no_reference",
                window=(0, 0),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )

        if not hyp:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=0,
                mode="empty",
                window=(self._committed, self._committed),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )

        candidate, matched_n, score, conf, backward, mode, window, local_match = self._search_best_candidate(hyp)

        repeated_candidate = candidate == self._last_candidate
        if repeated_candidate:
            self._same_candidate_hits += 1
        else:
            self._same_candidate_hits = 1

        zone_anchor = (candidate // 4) * 4
        if zone_anchor == self._last_zone_anchor and candidate >= self._committed:
            self._same_zone_hits += 1
        else:
            self._same_zone_hits = 1
        self._last_zone_anchor = zone_anchor

        advance = candidate - self._committed
        strong_accept = (
            not backward
            and advance >= 1
            and conf >= self.min_confidence
            and local_match >= 0.60
            and self._same_candidate_hits >= self.stable_hits
        )
        weak_forward = (
            not backward
            and advance >= 3
            and conf >= max(0.80, self.min_confidence + 0.16)
            and local_match >= 0.76
            and self._same_zone_hits >= 2
        )

        accepted = False
        soft_committed = False
        stable = False

        if strong_accept:
            self._committed = max(self._committed, candidate)
            accepted = True
            stable = True
        elif weak_forward:
            self._committed = max(self._committed, candidate)
            accepted = True
            soft_committed = True

        result = AlignmentResult(
            committed=self._committed,
            candidate=candidate,
            score=score,
            conf=conf,
            stable=stable,
            backward=backward,
            matched_n=matched_n,
            hyp_n=len(hyp),
            mode=mode,
            window=window,
            local_match=local_match,
            soft_committed=soft_committed,
            accepted=accepted,
            raw_text=hyp_raw,
            normalized_text=hyp,
            repeated_candidate=repeated_candidate,
            weak_forward=weak_forward,
        )

        self._last_candidate = candidate

        if self._forced_budget > 0:
            self._forced_budget -= 1
            if self._forced_budget <= 0:
                self._forced_center = None
                self._forced_window_back = None
                self._forced_window_ahead = None

        return result

    def _search_best_candidate(
        self,
        hyp: str,
    ) -> tuple[int, int, float, float, bool, str, tuple[int, int], float]:
        ref = self.reference_norm
        committed = self._committed

        start, end, mode = self._build_search_window(hyp)

        best_candidate = committed
        best_matched_n = 0
        best_score = -1e9
        best_conf = 0.0
        best_local_match = 0.0

        for cand in range(start, end + 1):
            seg = ref[cand : min(len(ref), cand + max(len(hyp) + 10, 18))]
            if not seg:
                continue

            sim, matched_n = self._substring_similarity(hyp, seg)
            prefix = self._prefix_match_ratio(hyp, seg)
            suffix = self._suffix_match_ratio(hyp, seg)
            bigram = self._bigram_overlap(hyp, seg)
            local_match = 0.45 * sim + 0.25 * prefix + 0.20 * suffix + 0.10 * bigram

            advance = cand - committed
            backward = advance < 0

            score = (
                10.0 * sim
                + 4.2 * prefix
                + 3.4 * suffix
                + 2.8 * bigram
                + 0.12 * matched_n
                - 0.14 * abs(advance)
                - (1.8 if backward else 0.0)
            )

            if not backward and matched_n >= min(4, len(hyp)):
                score += 0.8
            if not backward and suffix >= 0.68:
                score += 0.5
            if backward and sim < 0.62:
                score -= 1.2

            conf = max(
                0.0,
                min(
                    0.999,
                    0.55 * sim + 0.18 * prefix + 0.14 * suffix + 0.08 * bigram + 0.05 * (0.0 if backward else 1.0),
                ),
            )

            if score > best_score:
                best_score = score
                best_conf = conf
                best_local_match = local_match
                best_matched_n = matched_n
                best_candidate = min(len(ref), cand + max(matched_n, int(round(len(hyp) * max(sim, 0.35)))))

        backward = best_candidate < committed
        if backward and best_conf < 0.58:
            best_candidate = committed
            best_score = min(best_score, -0.8)
            mode = "backward_rejected"
        elif best_conf < 0.44 and mode == "normal":
            mode = "low_confidence"

        return (
            best_candidate,
            best_matched_n,
            float(best_score),
            float(best_conf),
            bool(backward),
            mode,
            (start, end),
            float(best_local_match),
        )

    def _build_search_window(self, hyp: str) -> tuple[int, int, str]:
        ref = self.reference_norm
        committed = self._committed

        if self._forced_center is not None and self._forced_budget > 0:
            center = max(committed, int(self._forced_center))
            back = int(self._forced_window_back or self.window_back)
            ahead = int(self._forced_window_ahead or self.window_ahead)
            return (
                max(0, center - back),
                min(len(ref), center + ahead),
                "forced_recenter",
            )

        long_partial = len(hyp) >= 12
        repeated_zone = self._same_zone_hits >= 3
        recovery_mode = long_partial or repeated_zone

        back = self.window_back + (6 if recovery_mode else 0)
        ahead = self.window_ahead + (10 if recovery_mode else 0)

        return (
            max(0, committed - back),
            min(len(ref), committed + ahead),
            "recovery" if recovery_mode else "normal",
        )

    def _substring_similarity(self, hyp: str, seg: str) -> tuple[float, int]:
        if not hyp or not seg:
            return 0.0, 0

        n = len(hyp)
        m = len(seg)
        best_sim = 0.0
        best_match = 0

        min_len = max(1, int(round(n * 0.70)))
        max_len = min(m, n + 6)

        for take in range(min_len, max_len + 1):
            ref_sub = seg[:take]
            dist = self._edit_distance_banded(hyp, ref_sub, band=max(2, abs(len(hyp) - len(ref_sub)) + 3))
            denom = max(len(hyp), len(ref_sub), 1)
            sim = max(0.0, 1.0 - dist / denom)
            matched = max(0, len(hyp) - dist)
            if sim > best_sim:
                best_sim = sim
                best_match = matched

        return best_sim, best_match

    def _edit_distance_banded(self, a: str, b: str, band: int) -> int:
        n = len(a)
        m = len(b)
        inf = 10**9
        prev = [inf] * (m + 1)
        prev[0] = 0
        for j in range(1, m + 1):
            prev[j] = j
        for i in range(1, n + 1):
            cur = [inf] * (m + 1)
            lo = max(1, i - band)
            hi = min(m, i + band)
            if lo == 1:
                cur[0] = i
            for j in range(lo, hi + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            prev = cur
        return int(prev[m])

    def _prefix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(n):
            if a[i] != b[i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))

    def _suffix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(1, n + 1):
            if a[-i] != b[-i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))

    def _bigram_overlap(self, a: str, b: str) -> float:
        if len(a) < 2 or len(b) < 2:
            return 0.0
        aset = {a[i : i + 2] for i in range(len(a) - 1)}
        bset = {b[i : i + 2] for i in range(len(b) - 1)}
        if not aset:
            return 0.0
        return _safe_ratio(len(aset & bset), len(aset))
