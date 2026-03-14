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
        input_latency_adapt_ms: float = 12.0,
        output_latency_adapt_ms: float = 18.0,
    ) -> None:
        self.input_latency_adapt_ms = float(input_latency_adapt_ms)
        self.output_latency_adapt_ms = float(output_latency_adapt_ms)

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._first_signal_active_at_sec = 0.0
        self._first_progress_at_sec = 0.0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._first_signal_active_at_sec = 0.0
        self._first_progress_at_sec = 0.0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.48:
            self._last_active_at_sec = signal_quality.observed_at_sec
            if self._first_signal_active_at_sec <= 0.0:
                self._first_signal_active_at_sec = signal_quality.observed_at_sec

    def observe_progress(self, progress_event_at_sec: float) -> None:
        if self._state is None:
            return
        if progress_event_at_sec <= 0.0:
            return

        if self._first_progress_at_sec <= 0.0:
            self._first_progress_at_sec = progress_event_at_sec

        if self._first_signal_active_at_sec > 0.0:
            delta_ms = max(0.0, (progress_event_at_sec - self._first_signal_active_at_sec) * 1000.0)

            adapted_input = min(
                260.0,
                max(10.0, self._state.estimated_input_latency_ms * 0.82 + delta_ms * 0.18),
            )
            self._state.estimated_input_latency_ms = adapted_input

            if delta_ms > 120.0:
                self._state.estimated_output_latency_ms = min(
                    280.0,
                    self._state.estimated_output_latency_ms + self.output_latency_adapt_ms * 0.10,
                )

            self._state.confidence = min(0.92, self._state.confidence + 0.12)
            self._state.calibrated = self._state.confidence >= 0.55

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state