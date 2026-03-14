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
    gain_soft_duck: float = 0.42

    recover_after_seek_sec: float = 0.60
    startup_grace_sec: float = 0.80
    low_confidence_hold_sec: float = 0.60
    bootstrapping_sec: float = 1.80

    guide_play_sec: float = 2.20
    no_progress_hold_min_play_sec: float = 4.00
    speaking_recent_sec: float = 0.90
    progress_stale_sec: float = 1.10
    hold_trend_sec: float = 0.75
    hold_extra_lead_sec: float = 0.18
    low_confidence_continue_sec: float = 1.40

    tracking_quality_hold_min: float = 0.60
    tracking_quality_seek_min: float = 0.72

    resume_from_hold_event_fresh_sec: float = 0.45
    resume_from_hold_speaking_lead_slack_sec: float = 0.45
    reacquire_soft_duck_sec: float = 2.00

    disable_seek: bool = False