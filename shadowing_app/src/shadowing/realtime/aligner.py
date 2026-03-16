from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


@dataclass(slots=True)
class AlignmentCandidate:
    ref_idx: int
    confidence: float
    local_match_ratio: float
    matched_chars: int
    source_text: str


@dataclass(slots=True)
class AlignmentTrackingQuality:
    local_score: float
    continuity_score: float
    confidence_score: float
    overall_score: float


@dataclass(slots=True)
class AlignmentSnapshot:
    candidate_ref_idx: int
    committed_ref_idx: int
    confidence: float
    stable: bool
    local_match_ratio: float
    repeat_penalty: float
    emitted_at_sec: float
    tracking_mode: str
    tracking_quality: AlignmentTrackingQuality


class RealtimeAligner:
    def __init__(
        self,
        *,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_hits: int = 2,
        min_confidence: float = 0.60,
        debug: bool = False,
    ) -> None:
        self.window_back = max(0, int(window_back))
        self.window_ahead = max(1, int(window_ahead))
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.debug = bool(debug)

        self._tokens: list[dict[str, Any]] = []
        self._norm_tokens: list[str] = []
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0

    def reset(self, reference_tokens: list[dict[str, Any]]) -> None:
        self._tokens = list(reference_tokens or [])
        self._norm_tokens = [_normalize_text(x.get("text", "")) for x in self._tokens]
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0

    def update(
        self,
        *,
        partial_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot | None:
        if not self._tokens:
            return None

        norm = _normalize_text(partial_text)
        if not norm:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text="",
                emitted_at_sec=emitted_at_sec,
            )

        search_start = max(0, self._committed_ref_idx - self.window_back)
        search_end = min(len(self._tokens), self._committed_ref_idx + self.window_ahead + 1)

        best = self._scan_candidates(
            norm_text=norm,
            search_start=search_start,
            search_end=search_end,
        )

        if best is None:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text=norm,
                emitted_at_sec=emitted_at_sec,
            )

        if best.ref_idx == self._last_candidate_ref_idx:
            self._same_candidate_run += 1
        else:
            self._same_candidate_run = 1
            self._last_candidate_ref_idx = best.ref_idx

        stable = (
            best.confidence >= self.min_confidence
            and self._same_candidate_run >= self.stable_hits
        )

        if stable and best.ref_idx >= self._committed_ref_idx:
            self._committed_ref_idx = best.ref_idx

        snapshot = self._build_snapshot(
            candidate_ref_idx=best.ref_idx,
            confidence=best.confidence,
            local_match_ratio=best.local_match_ratio,
            matched_chars=best.matched_chars,
            source_text=best.source_text,
            emitted_at_sec=emitted_at_sec,
        )

        if self.debug:
            logger.info(
                "align: partial=%r candidate=%s committed=%s conf=%.3f stable=%s ratio=%.3f",
                partial_text,
                snapshot.candidate_ref_idx,
                snapshot.committed_ref_idx,
                snapshot.confidence,
                snapshot.stable,
                snapshot.local_match_ratio,
            )
        self._last_partial_text = norm
        self._last_emitted_at_sec = float(emitted_at_sec)
        return snapshot

    def _scan_candidates(
        self,
        *,
        norm_text: str,
        search_start: int,
        search_end: int,
    ) -> AlignmentCandidate | None:
        best: AlignmentCandidate | None = None
        for idx in range(search_start, search_end):
            candidate = self._score_candidate(idx=idx, norm_text=norm_text)
            if candidate is None:
                continue
            if best is None:
                best = candidate
                continue

            if candidate.confidence > best.confidence + 1e-6:
                best = candidate
            elif abs(candidate.confidence - best.confidence) <= 1e-6:
                if candidate.ref_idx > best.ref_idx:
                    best = candidate
        return best

    def _score_candidate(self, *, idx: int, norm_text: str) -> AlignmentCandidate | None:
        if idx < 0 or idx >= len(self._norm_tokens):
            return None

        token_text = self._norm_tokens[idx]
        if not token_text:
            return None

        overlap = self._longest_common_subsequence_approx(norm_text, token_text)
        if overlap <= 0:
            return None

        local_match_ratio = overlap / max(1, len(token_text))
        source_cover_ratio = overlap / max(1, len(norm_text))

        continuity_bonus = 0.0
        if idx == self._committed_ref_idx:
            continuity_bonus += 0.08
        elif idx == self._committed_ref_idx + 1:
            continuity_bonus += 0.06
        elif idx > self._committed_ref_idx + 1:
            jump = idx - self._committed_ref_idx
            continuity_bonus -= min(0.14, 0.015 * jump)
        elif idx < self._committed_ref_idx:
            back = self._committed_ref_idx - idx
            continuity_bonus -= min(0.18, 0.03 * back)

        confidence = (
            0.58 * local_match_ratio
            + 0.26 * source_cover_ratio
            + continuity_bonus
        )
        confidence = max(0.0, min(1.0, confidence))

        return AlignmentCandidate(
            ref_idx=idx,
            confidence=confidence,
            local_match_ratio=max(0.0, min(1.0, local_match_ratio)),
            matched_chars=overlap,
            source_text=norm_text,
        )

    def _build_snapshot(
        self,
        *,
        candidate_ref_idx: int,
        confidence: float,
        local_match_ratio: float,
        matched_chars: int,
        source_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot:
        candidate_ref_idx = _clamp(candidate_ref_idx, 0, max(0, len(self._tokens) - 1))
        committed_ref_idx = _clamp(self._committed_ref_idx, 0, max(0, len(self._tokens) - 1))
        stable = confidence >= self.min_confidence and self._same_candidate_run >= self.stable_hits

        repeat_penalty = 0.0
        if committed_ref_idx > candidate_ref_idx:
            repeat_penalty = min(1.0, 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx == committed_ref_idx and source_text == self._last_partial_text:
            repeat_penalty = min(1.0, 0.08 * self._same_candidate_run)

        continuity_score = 1.0
        if candidate_ref_idx < committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx > committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.04 * (candidate_ref_idx - committed_ref_idx))

        confidence_score = float(confidence)
        overall_score = (
            0.40 * float(local_match_ratio)
            + 0.30 * continuity_score
            + 0.30 * confidence_score
        )
        overall_score = max(0.0, min(1.0, overall_score))

        if confidence < 0.20:
            tracking_mode = "LOST"
        elif stable and confidence >= self.min_confidence:
            tracking_mode = "LOCKED"
        elif confidence >= max(0.35, self.min_confidence - 0.12):
            tracking_mode = "WEAK_LOCKED"
        else:
            tracking_mode = "REACQUIRING"

        return AlignmentSnapshot(
            candidate_ref_idx=int(candidate_ref_idx),
            committed_ref_idx=int(committed_ref_idx),
            confidence=float(max(0.0, min(1.0, confidence))),
            stable=bool(stable),
            local_match_ratio=float(max(0.0, min(1.0, local_match_ratio))),
            repeat_penalty=float(max(0.0, min(1.0, repeat_penalty))),
            emitted_at_sec=float(emitted_at_sec),
            tracking_mode=str(tracking_mode),
            tracking_quality=AlignmentTrackingQuality(
                local_score=float(max(0.0, min(1.0, local_match_ratio))),
                continuity_score=float(max(0.0, min(1.0, continuity_score))),
                confidence_score=float(max(0.0, min(1.0, confidence_score))),
                overall_score=float(max(0.0, min(1.0, overall_score))),
            ),
        )

    def _longest_common_subsequence_approx(self, a: str, b: str) -> int:
        """
        这里用一个轻量近似，不做 O(n*m) 真 LCS，避免实时路径太重。
        规则：
        - 先取最长公共子串长度
        - 再用前缀 / 后缀命中稍微补一点
        """
        if not a or not b:
            return 0

        longest_substring = self._longest_common_substring_len(a, b)
        prefix = 0
        for x, y in zip(a, b):
            if x != y:
                break
            prefix += 1

        suffix = 0
        for x, y in zip(a[::-1], b[::-1]):
            if x != y:
                break
            suffix += 1

        return max(longest_substring, prefix, suffix)

    def _longest_common_substring_len(self, a: str, b: str) -> int:
        if not a or not b:
            return 0

        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        best = 0
        for win in range(len(shorter), 0, -1):
            if win <= best:
                break
            for i in range(0, len(shorter) - win + 1):
                sub = shorter[i : i + win]
                if sub in longer:
                    return win
        return best