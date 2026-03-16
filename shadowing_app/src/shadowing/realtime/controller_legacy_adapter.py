from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from shadowing.realtime.controller import ControlDecision, PlaybackController


def _to_plain_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    out: dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        out[name] = value
    return out


class LegacyControllerAdapter:
    """
    给旧调用方用的薄适配层：
    - 老代码如果还期待 dict 形式 action，可先通过这个 adapter 过渡
    - 等全链路改完，再直接删掉这个文件
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.controller = PlaybackController(config=config)

    def reset(self, *, started_at_sec: float) -> None:
        self.controller.reset(started_at_sec=started_at_sec)

    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> dict[str, Any]:
        decision: ControlDecision = self.controller.decide(
            now_sec=now_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            progress_estimate=progress_estimate,
            latency_state=latency_state,
        )
        payload = _to_plain_dict(decision)
        payload.setdefault("action", decision.action)
        payload.setdefault("reason", decision.reason)
        payload.setdefault("target_gain", decision.target_gain)
        payload.setdefault("seek_to_ref_time_sec", decision.seek_to_ref_time_sec)
        return payload