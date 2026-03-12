from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from shadowing.types import AlignResult, AsrEvent, ControlFeatures, PlaybackStatus


@dataclass(slots=True)
class StateEstimatorConfig:
    lead_ema_alpha: float = 0.35

    speaking_window_sec: float = 0.6
    partial_rate_window_sec: float = 2.0

    min_target_lead_sec: float = 0.08
    base_target_lead_sec: float = 0.15
    max_target_lead_sec: float = 0.35

    gain_normal: float = 1.0
    gain_soft: float = 0.75
    gain_following: float = 0.55

    # 关键新增：ducking 保持时间
    duck_hold_sec: float = 0.45


class ControlStateEstimator:
    """
    从 playback/alignment/asr 中提炼更稳定的控制特征。
    """

    def __init__(self, config: StateEstimatorConfig | None = None) -> None:
        self.config = config or StateEstimatorConfig()

        self._lead_ema: float | None = None
        self._last_lead_ema: float | None = None

        self._partial_times: deque[float] = deque()
        self._hold_times: deque[float] = deque()

        self._last_asr_event_at: float | None = None

        # 关键新增：最近一次“稳定跟读”时间，用于保持 ducking
        self._last_following_at: float | None = None

    def note_asr_event(self, event: AsrEvent) -> None:
        now = time.monotonic()
        self._last_asr_event_at = now

        if event.event_type.value == "partial":
            self._partial_times.append(now)
            self._trim_deque(self._partial_times, now, self.config.partial_rate_window_sec)

    def note_hold(self) -> None:
        now = time.monotonic()
        self._hold_times.append(now)
        self._trim_deque(self._hold_times, now, 5.0)

    def update(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlFeatures:
        now = time.monotonic()

        lead_raw: float | None = None
        alignment_conf = 0.0
        alignment_stable = False

        if alignment is not None:
            lead_raw = playback.t_ref_heard_sec - alignment.ref_time_sec
            alignment_conf = alignment.confidence
            alignment_stable = alignment.stable

        if lead_raw is not None:
            if self._lead_ema is None:
                self._lead_ema = lead_raw
            else:
                self._lead_ema = (
                    self.config.lead_ema_alpha * lead_raw
                    + (1.0 - self.config.lead_ema_alpha) * self._lead_ema
                )

        lead_slope: float | None = None
        if self._lead_ema is not None and self._last_lead_ema is not None:
            lead_slope = self._lead_ema - self._last_lead_ema
        self._last_lead_ema = self._lead_ema

        self._trim_deque(self._partial_times, now, self.config.partial_rate_window_sec)
        self._trim_deque(self._hold_times, now, 5.0)

        recent_partial_rate = len(self._partial_times) / max(self.config.partial_rate_window_sec, 1e-6)
        recent_hold_count = len(self._hold_times)

        user_speaking = False
        if self._last_asr_event_at is not None:
            user_speaking = (now - self._last_asr_event_at) <= self.config.speaking_window_sec

        dynamic_target_lead = self._compute_dynamic_target_lead(
            alignment_conf=alignment_conf,
            alignment_stable=alignment_stable,
            recent_hold_count=recent_hold_count,
        )

        suggested_gain = self._compute_suggested_gain(
            now=now,
            user_speaking=user_speaking,
            alignment_stable=alignment_stable,
            alignment_conf=alignment_conf,
        )

        return ControlFeatures(
            lead_raw=lead_raw,
            lead_ema=self._lead_ema,
            lead_slope=lead_slope,
            alignment_conf=alignment_conf,
            alignment_stable=alignment_stable,
            user_speaking=user_speaking,
            recent_partial_rate=recent_partial_rate,
            recent_hold_count=recent_hold_count,
            dynamic_target_lead=dynamic_target_lead,
            suggested_gain=suggested_gain,
            playback_state=playback.state.value,
        )

    def _compute_dynamic_target_lead(
        self,
        alignment_conf: float,
        alignment_stable: bool,
        recent_hold_count: int,
    ) -> float:
        target = self.config.base_target_lead_sec

        if alignment_stable and alignment_conf >= 0.85:
            target += 0.05

        if recent_hold_count >= 2:
            target -= 0.06

        target = min(max(target, self.config.min_target_lead_sec), self.config.max_target_lead_sec)
        return target

    def _compute_suggested_gain(
        self,
        now: float,
        user_speaking: bool,
        alignment_stable: bool,
        alignment_conf: float,
    ) -> float:
        # 进入“稳定跟读”态时，记录时间戳
        if user_speaking and alignment_stable and alignment_conf >= 0.75:
            self._last_following_at = now
            return self.config.gain_following

        # 关键补丁：ducking 保持
        if self._last_following_at is not None:
            if (now - self._last_following_at) <= self.config.duck_hold_sec:
                return self.config.gain_following

        if user_speaking:
            return self.config.gain_soft

        return self.config.gain_normal

    @staticmethod
    def _trim_deque(dq: deque[float], now: float, window_sec: float) -> None:
        while dq and (now - dq[0]) > window_sec:
            dq.popleft()