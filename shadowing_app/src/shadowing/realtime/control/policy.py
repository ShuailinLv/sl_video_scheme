from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.15
    hold_if_lead_sec: float = 0.45
    resume_if_lead_sec: float = 0.18
    seek_if_lag_sec: float = -0.90
    min_confidence: float = 0.60
    seek_cooldown_sec: float = 0.40