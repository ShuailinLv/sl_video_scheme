from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StableAnchorConfig:
    min_tracking_q: float = 0.78
    min_confidence: float = 0.78
    min_score: float = 0.0
    same_candidate_hits: int = 2
    backward_penalty: float = 0.35
    unstable_penalty: float = 0.20


@dataclass
class StableAnchorDecision:
    stable_anchor: bool
    anchor_trust: float
    same_candidate_hits: int


class StableAnchorTracker:
    """
    维护 candidate 连续命中计数，并输出 stable_anchor / anchor_trust。

    规则：
    - backward 一票否决 stable_anchor
    - tracking_quality / confidence / score 达标
    - candidate 连续命中达到 same_candidate_hits
    """

    def __init__(self, config: StableAnchorConfig | None = None) -> None:
        self.config = config or StableAnchorConfig()
        self._last_candidate_idx: int | None = None
        self._same_candidate_hits: int = 0

    def reset(self) -> None:
        self._last_candidate_idx = None
        self._same_candidate_hits = 0

    def update(
        self,
        *,
        candidate_idx: int | None,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
    ) -> StableAnchorDecision:
        if candidate_idx is None:
            self._last_candidate_idx = None
            self._same_candidate_hits = 0
            return StableAnchorDecision(
                stable_anchor=False,
                anchor_trust=0.0,
                same_candidate_hits=0,
            )

        if self._last_candidate_idx == candidate_idx:
            self._same_candidate_hits += 1
        else:
            self._last_candidate_idx = candidate_idx
            self._same_candidate_hits = 1

        anchor_trust = self._compute_anchor_trust(
            confidence=confidence,
            tracking_quality=tracking_quality,
            score=score,
            backward=backward,
            same_hits=self._same_candidate_hits,
        )

        stable_anchor = (
            not backward
            and tracking_quality >= self.config.min_tracking_q
            and confidence >= self.config.min_confidence
            and score >= self.config.min_score
            and self._same_candidate_hits >= self.config.same_candidate_hits
        )

        return StableAnchorDecision(
            stable_anchor=stable_anchor,
            anchor_trust=anchor_trust,
            same_candidate_hits=self._same_candidate_hits,
        )

    def _compute_anchor_trust(
        self,
        *,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
        same_hits: int,
    ) -> float:
        # 置信度和 tracking_quality 为主体
        trust = 0.55 * float(confidence) + 0.35 * float(tracking_quality)

        # score 用作轻微修正，假定 score >= 0 越大越好
        if score >= 0:
            trust += min(0.10, score / 100.0)
        else:
            trust -= min(0.10, abs(score) / 50.0)

        # candidate 连续命中加分
        trust += min(0.12, 0.04 * max(0, same_hits - 1))

        if backward:
            trust -= self.config.backward_penalty

        if same_hits < self.config.same_candidate_hits:
            trust -= self.config.unstable_penalty

        return max(0.0, min(1.0, trust))