from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShadowLagEstimatorConfig:
    init_sec: float = 1.20
    min_sec: float = 0.35
    max_sec: float = 2.40
    ema_alpha: float = 0.18
    update_min_tracking_q: float = 0.78
    update_min_anchor_trust: float = 0.78


class ShadowLagEstimator:
    """
    估计用户自然跟读相对参考音频的滞后时间（shadow offset）。

    raw_lead_sec = reference_time - user_time
    effective_lead_sec = raw_lead_sec - shadow_offset_sec

    只有在“稳定锚点 + tracking质量足够高”的情况下才更新 shadow_offset，
    防止错误对齐把 offset 拉飞。
    """

    def __init__(self, config: ShadowLagEstimatorConfig | None = None) -> None:
        self.config = config or ShadowLagEstimatorConfig()
        self._offset_sec = float(self.config.init_sec)

    @property
    def offset_sec(self) -> float:
        return float(self._offset_sec)

    def reset(self) -> None:
        self._offset_sec = float(self.config.init_sec)

    def set_offset(self, value_sec: float) -> None:
        self._offset_sec = self._clamp(value_sec)

    def update_from_anchor(
        self,
        raw_lead_sec: float | None,
        *,
        stable_anchor: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> float:
        """
        用高可信稳定锚点更新用户自然滞后。
        """
        if raw_lead_sec is None:
            return self.offset_sec

        if not stable_anchor:
            return self.offset_sec

        if tracking_quality < self.config.update_min_tracking_q:
            return self.offset_sec

        if anchor_trust < self.config.update_min_anchor_trust:
            return self.offset_sec

        alpha = self.config.ema_alpha
        target = self._clamp(raw_lead_sec)
        self._offset_sec = self._clamp((1.0 - alpha) * self._offset_sec + alpha * target)
        return self.offset_sec

    def effective_lead(self, raw_lead_sec: float | None) -> float | None:
        if raw_lead_sec is None:
            return None
        return float(raw_lead_sec) - self.offset_sec

    def _clamp(self, value_sec: float) -> float:
        return max(self.config.min_sec, min(self.config.max_sec, float(value_sec)))