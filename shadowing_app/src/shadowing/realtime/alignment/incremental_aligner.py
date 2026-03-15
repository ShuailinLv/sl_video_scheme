from __future__ import annotations

from dataclasses import dataclass
import re
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


def _lcp_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _char_overlap_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    matched = 0
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] == b[i]:
            matched += 1
    return matched / max(1, len(a))


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
    def __init__(
        self,
        reference_text: str | Sequence[str] | None = None,
        *,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_frames: int = 2,
        min_confidence: float = 0.60,
        backward_lock_frames: int = 3,
        clause_boundary_bonus: float = 0.15,
        cross_clause_backward_extra_penalty: float = 0.20,
        debug: bool = False,
        max_hyp_tokens: int = 16,
        weak_commit_min_conf: float = 0.82,
        weak_commit_min_local_match: float = 0.80,
        weak_commit_min_advance: int = 3,
    ) -> None:
        self.debug = bool(debug)
        self.window_back = int(window_back)
        self.window_ahead = int(window_ahead)
        self.stable_frames = max(1, int(stable_frames))
        self.min_confidence = float(min_confidence)
        self.backward_lock_frames = int(backward_lock_frames)
        self.clause_boundary_bonus = float(clause_boundary_bonus)
        self.cross_clause_backward_extra_penalty = float(cross_clause_backward_extra_penalty)
        self.max_hyp_tokens = int(max_hyp_tokens)

        self.weak_commit_min_conf = float(weak_commit_min_conf)
        self.weak_commit_min_local_match = float(weak_commit_min_local_match)
        self.weak_commit_min_advance = int(weak_commit_min_advance)

        self.reference_text = ""
        self.reference_norm = ""

        self._committed = 0
        self._last_candidate = 0
        self._same_candidate_repeat = 0
        self._last_zone_anchor = 0
        self._same_forward_zone_repeat = 0

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
        if committed is not None:
            self._committed = max(0, min(len(self.reference_norm), int(committed)))
        else:
            self._committed = 0
        self._last_candidate = self._committed
        self._same_candidate_repeat = 0
        self._last_zone_anchor = self._committed
        self._same_forward_zone_repeat = 0

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
                score=-1.5,
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

        repeated_candidate = False
        if candidate == self._last_candidate:
            self._same_candidate_repeat += 1
            repeated_candidate = True
        else:
            self._same_candidate_repeat = 0

        zone_anchor = (candidate // 3) * 3
        if zone_anchor == self._last_zone_anchor and candidate >= self._committed:
            self._same_forward_zone_repeat += 1
        else:
            self._same_forward_zone_repeat = 0
        self._last_zone_anchor = zone_anchor

        advance = candidate - self._committed

        hard_commit = (
            not backward
            and advance >= 1
            and conf >= self.min_confidence
            and local_match >= 0.62
            and self._same_candidate_repeat >= (self.stable_frames - 1)
        )

        weak_forward = (
            not backward
            and advance >= self.weak_commit_min_advance
            and conf >= self.weak_commit_min_conf
            and local_match >= self.weak_commit_min_local_match
            and self._same_forward_zone_repeat >= 1
        )

        accepted = False
        soft_committed = False
        stable = False

        if hard_commit:
            self._committed = max(self._committed, candidate)
            accepted = True
            stable = True
        elif weak_forward:
            self._committed = max(self._committed, candidate)
            accepted = True
            soft_committed = True
            stable = False

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

        if self.debug:
            self._print_debug(result)

        return result

    def _search_best_candidate(
        self,
        hyp: str,
    ) -> tuple[int, int, float, float, bool, str, tuple[int, int], float]:
        ref = self.reference_norm
        committed = self._committed

        start = max(0, committed - self.window_back)
        end = min(len(ref), committed + self.window_ahead)

        best_candidate = committed
        best_matched = 0
        best_score = -1e9
        best_conf = 0.0
        best_local_match = 0.0
        best_mode = "normal"

        for cand in range(start, end + 1):
            max_take = min(len(hyp), len(ref) - cand)
            if max_take <= 0:
                continue

            ref_seg = ref[cand : cand + max_take]
            matched = _lcp_len(hyp, ref_seg)

            local_match = _char_overlap_ratio(
                hyp[: min(12, len(hyp))],
                ref_seg[: min(12, len(ref_seg))],
            )

            advance = cand - committed
            backward = advance < 0

            score = (
                matched * 3.2
                + local_match * 7.0
                - abs(advance) * 0.30
                - (2.5 if backward else 0.0)
            )

            conf = max(
                0.0,
                min(
                    0.999,
                    0.58 * _safe_ratio(matched, len(hyp))
                    + 0.32 * local_match
                    + 0.10 * (1.0 if not backward else 0.0),
                ),
            )

            if not backward and matched >= min(3, len(hyp)):
                score += 1.2
                conf = min(0.999, conf + 0.04)

            if not backward and matched <= 2 and local_match >= 0.84:
                score += 1.3
                conf = min(0.999, conf + 0.06)

            if advance > self.window_ahead * 0.7 and matched <= 1 and local_match < 0.55:
                score -= 2.5
                conf = max(0.0, conf - 0.10)

            if score > best_score:
                best_candidate = cand + matched
                if matched <= 2 and not backward and local_match >= 0.84:
                    best_candidate = max(best_candidate, min(cand + max_take, cand + matched + 2))
                best_matched = matched
                best_score = score
                best_conf = conf
                best_local_match = local_match
                best_mode = "backward" if backward else "normal"

        backward = best_candidate < committed
        if backward and best_conf <= 0.55:
            best_candidate = committed
            best_mode = "backward"
            best_score = min(best_score, -1.5)

        return (
            best_candidate,
            best_matched,
            best_score,
            best_conf,
            backward,
            best_mode,
            (start, end),
            best_local_match,
        )

    def _print_debug(self, result: AlignmentResult) -> None:
        tag = "[ALIGN]" if result.accepted else "[ALIGN-REJECT]"
        extra = " soft_commit=True" if result.soft_committed else ""
        if result.weak_forward and not result.soft_committed:
            extra += " weak_forward=True"

        print(
            f"{tag} committed={self._committed} "
            f"candidate={result.candidate} "
            f"score={result.score:.3f} "
            f"conf={result.conf:.3f} "
            f"stable={result.stable} "
            f"backward={result.backward} "
            f"matched_n={result.matched_n} "
            f"hyp_n={result.hyp_n} "
            f"mode={result.mode} "
            f"window=({result.window[0]},{result.window[1]}) "
            f"local_match={result.local_match:.3f}"
            f"{extra}"
        )