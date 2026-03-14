from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PartialGuardConfig:
    backward_hits_to_reset: int = 2
    low_q_threshold: float = 0.45
    low_q_hold_sec: float = 0.80
    no_commit_sec: float = 1.20
    max_partial_chars: int = 48
    long_partial_low_trust_threshold: float = 0.55


@dataclass
class PartialGuardState:
    backward_hits: int = 0
    low_q_elapsed_sec: float = 0.0
    no_commit_elapsed_sec: float = 0.0
    partial_reset_recommended: bool = False
    reason: str = ""


class PartialGuard:
    """
    监控 partial 污染，必要时建议 reset decoder stream。

    典型触发：
    - backward 连续两次
    - tracking quality 持续低
    - 很久没有 committed 推进
    - partial 很长但锚点信任很低
    """

    def __init__(self, config: PartialGuardConfig | None = None) -> None:
        self.config = config or PartialGuardConfig()
        self._state = PartialGuardState()

    @property
    def state(self) -> PartialGuardState:
        return self._state

    def reset(self) -> None:
        self._state = PartialGuardState()

    def update(
        self,
        *,
        dt_sec: float,
        partial_text: str,
        committed_advanced: bool,
        backward: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> PartialGuardState:
        s = self._state
        s.partial_reset_recommended = False
        s.reason = ""

        if backward:
            s.backward_hits += 1
        else:
            s.backward_hits = 0

        if tracking_quality < self.config.low_q_threshold:
            s.low_q_elapsed_sec += max(0.0, dt_sec)
        else:
            s.low_q_elapsed_sec = 0.0

        if committed_advanced:
            s.no_commit_elapsed_sec = 0.0
        else:
            s.no_commit_elapsed_sec += max(0.0, dt_sec)

        partial_len = len(partial_text or "")

        if s.backward_hits >= self.config.backward_hits_to_reset:
            s.partial_reset_recommended = True
            s.reason = f"backward_hits={s.backward_hits}"
            return s

        if s.low_q_elapsed_sec >= self.config.low_q_hold_sec:
            s.partial_reset_recommended = True
            s.reason = f"low_tracking_q_for={s.low_q_elapsed_sec:.3f}s"
            return s

        if s.no_commit_elapsed_sec >= self.config.no_commit_sec:
            s.partial_reset_recommended = True
            s.reason = f"no_commit_for={s.no_commit_elapsed_sec:.3f}s"
            return s

        if (
            partial_len >= self.config.max_partial_chars
            and anchor_trust < self.config.long_partial_low_trust_threshold
        ):
            s.partial_reset_recommended = True
            s.reason = f"long_partial_len={partial_len}_low_trust={anchor_trust:.3f}"
            return s

        return s