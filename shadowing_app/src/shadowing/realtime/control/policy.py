from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.18
    hold_if_lead_sec: float = 1.05
    resume_if_lead_sec: float = 0.36
    seek_if_lag_sec: float = -2.60
    min_confidence: float = 0.70
    seek_cooldown_sec: float = 2.20

    gain_following: float = 0.52
    gain_transition: float = 0.72
    gain_soft_duck: float = 0.36

    recover_after_seek_sec: float = 0.80
    startup_grace_sec: float = 3.20
    low_confidence_hold_sec: float = 2.20
    bootstrapping_sec: float = 2.20

    guide_play_sec: float = 3.20
    no_progress_hold_min_play_sec: float = 5.80
    speaking_recent_sec: float = 1.10
    progress_stale_sec: float = 1.45
    hold_trend_sec: float = 1.00
    hold_extra_lead_sec: float = 0.22
    low_confidence_continue_sec: float = 1.80

    tracking_quality_hold_min: float = 0.60
    tracking_quality_seek_min: float = 0.84

    resume_from_hold_event_fresh_sec: float = 0.60
    resume_from_hold_speaking_lead_slack_sec: float = 0.72
    reacquire_soft_duck_sec: float = 2.40

    disable_seek: bool = False

    bluetooth_long_session_target_lead_sec: float = 0.38
    bluetooth_long_session_hold_if_lead_sec: float = 1.35
    bluetooth_long_session_resume_if_lead_sec: float = 0.30
    bluetooth_long_session_seek_if_lag_sec: float = -3.20
    bluetooth_long_session_seek_cooldown_sec: float = 3.20
    bluetooth_long_session_progress_stale_sec: float = 1.75
    bluetooth_long_session_hold_trend_sec: float = 1.15
    bluetooth_long_session_tracking_quality_hold_min: float = 0.58
    bluetooth_long_session_tracking_quality_seek_min: float = 0.88
    bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec: float = 0.82
    bluetooth_long_session_gain_following: float = 0.50
    bluetooth_long_session_gain_transition: float = 0.66
    bluetooth_long_session_gain_soft_duck: float = 0.32