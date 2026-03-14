from __future__ import annotations

from dataclasses import dataclass

from shadowing.audio.device_profile import DeviceProfile
from shadowing.types import SignalQuality


@dataclass(slots=True)
class LatencyCalibrationState:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    confidence: float
    calibrated: bool


class LatencyCalibrator:
    def __init__(
        self,
        input_latency_adapt_ms: float = 8.0,
        output_latency_adapt_ms: float = 14.0,
        target_shadow_lead_sec: float = 0.15,
        min_tracking_quality: float = 0.82,
        min_sync_hits_before_update: int = 3,
    ) -> None:
        self.input_latency_adapt_ms = float(input_latency_adapt_ms)
        self.output_latency_adapt_ms = float(output_latency_adapt_ms)
        self.target_shadow_lead_sec = float(target_shadow_lead_sec)
        self.min_tracking_quality = float(min_tracking_quality)
        self.min_sync_hits_before_update = max(1, int(min_sync_hits_before_update))

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.48:
            self._last_active_at_sec = float(signal_quality.observed_at_sec)

    def observe_sync(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        user_ref_time_sec: float,
        tracking_quality: float,
        stable: bool,
        active_speaking: bool,
    ) -> None:
        if self._state is None:
            return
        if not stable:
            self._reliable_sync_hits = 0
            return
        if tracking_quality < self.min_tracking_quality:
            self._reliable_sync_hits = 0
            return
        if not active_speaking:
            self._reliable_sync_hits = 0
            return
        if self._last_active_at_sec <= 0.0:
            self._reliable_sync_hits = 0
            return
        if (float(now_sec) - self._last_active_at_sec) > 0.80:
            self._reliable_sync_hits = 0
            return

        lead_sec = float(playback_ref_time_sec) - float(user_ref_time_sec)
        if abs(lead_sec) > 3.0:
            self._reliable_sync_hits = 0
            return

        self._reliable_sync_hits += 1
        if self._reliable_sync_hits < self.min_sync_hits_before_update:
            return

        lead_error_sec = lead_sec - self.target_shadow_lead_sec
        lead_error_ms = lead_error_sec * 1000.0

        if lead_error_ms > 20.0:
            self._state.estimated_output_latency_ms = min(
                320.0,
                self._state.estimated_output_latency_ms + min(
                    self.output_latency_adapt_ms,
                    lead_error_ms * 0.10,
                ),
            )
        elif lead_error_ms < -20.0:
            self._state.estimated_output_latency_ms = max(
                10.0,
                self._state.estimated_output_latency_ms - min(
                    self.output_latency_adapt_ms,
                    abs(lead_error_ms) * 0.10,
                ),
            )

        if self._reliable_sync_hits >= (self.min_sync_hits_before_update + 3) and abs(lead_error_ms) > 60.0:
            direction = 1.0 if lead_error_ms > 0 else -1.0
            self._state.estimated_input_latency_ms = min(
                260.0,
                max(
                    10.0,
                    self._state.estimated_input_latency_ms + (self.input_latency_adapt_ms * direction * 0.18),
                ),
            )

        self._state.confidence = min(0.95, self._state.confidence + 0.035)
        self._state.calibrated = self._state.confidence >= 0.60

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state