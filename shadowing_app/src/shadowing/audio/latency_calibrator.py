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
        input_latency_adapt_ms: float = 4.0,
        output_latency_adapt_ms: float = 8.0,
        target_shadow_lead_sec: float = 0.15,
        min_tracking_quality: float = 0.86,
        min_sync_hits_before_update: int = 5,
        min_recent_signal_sec: float = 0.90,
        min_update_interval_sec: float = 0.80,
        min_error_ms_to_adjust: float = 45.0,
        max_error_ms_for_observation: float = 1200.0,
        consistency_tolerance_ms: float = 90.0,
    ) -> None:
        self.input_latency_adapt_ms = float(input_latency_adapt_ms)
        self.output_latency_adapt_ms = float(output_latency_adapt_ms)
        self.target_shadow_lead_sec = float(target_shadow_lead_sec)
        self.min_tracking_quality = float(min_tracking_quality)
        self.min_sync_hits_before_update = max(2, int(min_sync_hits_before_update))
        self.min_recent_signal_sec = float(min_recent_signal_sec)
        self.min_update_interval_sec = float(min_update_interval_sec)
        self.min_error_ms_to_adjust = float(min_error_ms_to_adjust)
        self.max_error_ms_for_observation = float(max_error_ms_for_observation)
        self.consistency_tolerance_ms = float(consistency_tolerance_ms)

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0
        self._last_reliable_error_ms: float | None = None
        self._last_update_at_sec = 0.0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0
        self._last_reliable_error_ms = None
        self._last_update_at_sec = 0.0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.52:
            self._last_active_at_sec = float(signal_quality.observed_at_sec)

    def observe_sync(
        self,
        *,
        playback_ref_time_sec: float,
        user_ref_time_sec: float,
        tracking_quality: float,
        stable: bool,
        active_speaking: bool,
    ) -> None:
        if self._state is None:
            return

        now_sec = max(float(playback_ref_time_sec), float(user_ref_time_sec))

        if not stable:
            self._reset_observation_run()
            return

        if tracking_quality < self.min_tracking_quality:
            self._reset_observation_run()
            return

        if not active_speaking:
            self._reset_observation_run()
            return

        if self._last_active_at_sec <= 0.0:
            self._reset_observation_run()
            return

        if (now_sec - self._last_active_at_sec) > self.min_recent_signal_sec:
            self._reset_observation_run()
            return

        lead_sec = float(playback_ref_time_sec) - float(user_ref_time_sec)
        lead_error_ms = (lead_sec - self.target_shadow_lead_sec) * 1000.0

        if abs(lead_error_ms) > self.max_error_ms_for_observation:
            self._reset_observation_run()
            return

        if self._last_reliable_error_ms is not None:
            if abs(lead_error_ms - self._last_reliable_error_ms) > self.consistency_tolerance_ms:
                self._reliable_sync_hits = 1
            else:
                self._reliable_sync_hits += 1
        else:
            self._reliable_sync_hits = 1

        self._last_reliable_error_ms = float(lead_error_ms)

        if self._reliable_sync_hits < self.min_sync_hits_before_update:
            self._state.confidence = min(0.80, self._state.confidence + 0.010)
            self._state.calibrated = self._state.confidence >= 0.60
            return

        if self._last_update_at_sec > 0.0 and (now_sec - self._last_update_at_sec) < self.min_update_interval_sec:
            self._state.confidence = min(0.88, self._state.confidence + 0.006)
            self._state.calibrated = self._state.confidence >= 0.60
            return

        if abs(lead_error_ms) < self.min_error_ms_to_adjust:
            self._state.confidence = min(0.92, self._state.confidence + 0.020)
            self._state.calibrated = self._state.confidence >= 0.60
            self._last_update_at_sec = now_sec
            self._reliable_sync_hits = max(self.min_sync_hits_before_update - 1, 0)
            return

        self._apply_output_latency_update(lead_error_ms)
        self._maybe_apply_input_latency_update(lead_error_ms)

        self._state.confidence = min(0.95, self._state.confidence + 0.030)
        self._state.calibrated = self._state.confidence >= 0.60
        self._last_update_at_sec = now_sec

        self._reliable_sync_hits = max(self.min_sync_hits_before_update - 2, 0)

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state

    def _apply_output_latency_update(self, lead_error_ms: float) -> None:
        assert self._state is not None

        bounded_error_ms = max(-300.0, min(300.0, float(lead_error_ms)))
        step_ms = min(
            self.output_latency_adapt_ms,
            max(1.5, abs(bounded_error_ms) * 0.06),
        )

        if bounded_error_ms > 0.0:
            self._state.estimated_output_latency_ms = min(
                320.0,
                self._state.estimated_output_latency_ms + step_ms,
            )
        else:
            self._state.estimated_output_latency_ms = max(
                10.0,
                self._state.estimated_output_latency_ms - step_ms,
            )

    def _maybe_apply_input_latency_update(self, lead_error_ms: float) -> None:
        assert self._state is not None

        if self._reliable_sync_hits < (self.min_sync_hits_before_update + 4):
            return

        if abs(lead_error_ms) < 140.0:
            return

        bounded_error_ms = max(-220.0, min(220.0, float(lead_error_ms)))
        direction = 1.0 if bounded_error_ms > 0.0 else -1.0
        step_ms = min(
            self.input_latency_adapt_ms,
            max(0.8, abs(bounded_error_ms) * 0.025),
        )

        self._state.estimated_input_latency_ms = min(
            260.0,
            max(
                10.0,
                self._state.estimated_input_latency_ms + direction * step_ms,
            ),
        )

    def _reset_observation_run(self) -> None:
        self._reliable_sync_hits = 0
        self._last_reliable_error_ms = None