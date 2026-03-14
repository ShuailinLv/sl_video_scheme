from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.15
    hold_if_lead_sec: float = 0.90
    resume_if_lead_sec: float = 0.28
    seek_if_lag_sec: float = -1.80
    min_confidence: float = 0.75
    seek_cooldown_sec: float = 1.20
    gain_following: float = 0.55
    gain_transition: float = 0.80
    recover_after_seek_sec: float = 0.60
    startup_grace_sec: float = 0.80
    low_confidence_hold_sec: float = 0.60