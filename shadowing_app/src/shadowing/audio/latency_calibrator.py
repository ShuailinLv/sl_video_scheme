from __future__ import annotations

from dataclasses import dataclass

from shadowing.audio.device_profile import DeviceProfile
from shadowing.types import SignalQuality


@dataclass(slots=True)
class LatencyCalibrationState:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    runtime_input_drift_ms: float
    runtime_output_drift_ms: float
    confidence: float
    calibrated: bool


class LatencyCalibrator:
    def __init__(
        self,
        input_latency_adapt_ms: float = 2.0,
        output_latency_adapt_ms: float = 4.0,
        target_shadow_lead_sec: float = 0.15,
        min_tracking_quality: float = 0.86,
        min_sync_hits_before_update: int = 5,
        min_recent_signal_sec: float = 0.90,
        min_update_interval_sec: float = 1.10,
        min_error_ms_to_adjust: float = 55.0,
        max_error_ms_for_observation: float = 1200.0,
        consistency_tolerance_ms: float = 90.0,
        max_runtime_output_drift_ms: float = 90.0,
        max_runtime_input_drift_ms: float = 50.0,
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
        self.max_runtime_output_drift_ms = float(max_runtime_output_drift_ms)
        self.max_runtime_input_drift_ms = float(max_runtime_input_drift_ms)

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0
        self._last_reliable_error_ms: float | None = None
        self._last_update_at_sec = 0.0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            runtime_input_drift_ms=0.0,
            runtime_output_drift_ms=0.0,
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
        allow_observation: bool = True,
    ) -> None:
        if self._state is None:
            return

        now_sec = max(float(playback_ref_time_sec), float(user_ref_time_sec))

        if not allow_observation:
            self._soft_reset_observation_run()
            return
        if not stable:
            self._soft_reset_observation_run()
            return
        if tracking_quality < self.min_tracking_quality:
            self._soft_reset_observation_run()
            return
        if not active_speaking:
            self._soft_reset_observation_run()
            return
        if self._last_active_at_sec <= 0.0:
            self._soft_reset_observation_run()
            return
        if (now_sec - self._last_active_at_sec) > self.min_recent_signal_sec:
            self._soft_reset_observation_run()
            return

        lead_sec = float(playback_ref_time_sec) - float(user_ref_time_sec)
        lead_error_ms = (lead_sec - self.target_shadow_lead_sec) * 1000.0

        if abs(lead_error_ms) > self.max_error_ms_for_observation:
            self._soft_reset_observation_run()
            return

        self._accumulate_reliable_observation(lead_error_ms)

        if self._reliable_sync_hits < self.min_sync_hits_before_update:
            self._increase_confidence(0.012, max_conf=0.78)
            return

        if self._last_update_at_sec > 0.0 and (now_sec - self._last_update_at_sec) < self.min_update_interval_sec:
            self._increase_confidence(0.008, max_conf=0.86)
            return

        if abs(lead_error_ms) < self.min_error_ms_to_adjust:
            self._increase_confidence(0.020, max_conf=0.92)
            self._last_update_at_sec = now_sec
            self._reliable_sync_hits = max(self.min_sync_hits_before_update - 1, 0)
            return

        self._apply_runtime_output_drift(lead_error_ms)
        self._maybe_apply_runtime_input_drift(lead_error_ms)
        self._clamp_runtime_drifts()

        self._increase_confidence(0.028, max_conf=0.95)
        self._last_update_at_sec = now_sec
        self._reliable_sync_hits = max(self.min_sync_hits_before_update - 2, 0)

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state

    def effective_output_latency_ms(self) -> float | None:
        if self._state is None:
            return None
        return float(self._state.estimated_output_latency_ms + self._state.runtime_output_drift_ms)

    def effective_input_latency_ms(self) -> float | None:
        if self._state is None:
            return None
        return float(self._state.estimated_input_latency_ms + self._state.runtime_input_drift_ms)

    def _accumulate_reliable_observation(self, lead_error_ms: float) -> None:
        if self._last_reliable_error_ms is not None:
            if abs(lead_error_ms - self._last_reliable_error_ms) > self.consistency_tolerance_ms:
                self._reliable_sync_hits = 1
            else:
                self._reliable_sync_hits += 1
        else:
            self._reliable_sync_hits = 1

        self._last_reliable_error_ms = float(lead_error_ms)

    def _increase_confidence(self, delta: float, *, max_conf: float) -> None:
        assert self._state is not None
        self._state.confidence = min(float(max_conf), self._state.confidence + float(delta))
        self._state.calibrated = self._state.confidence >= 0.60

    def _apply_runtime_output_drift(self, lead_error_ms: float) -> None:
        assert self._state is not None

        bounded_error_ms = max(-260.0, min(260.0, float(lead_error_ms)))
        step_ms = min(self.output_latency_adapt_ms, max(1.0, abs(bounded_error_ms) * 0.045))

        if bounded_error_ms > 0.0:
            self._state.runtime_output_drift_ms += step_ms
        else:
            self._state.runtime_output_drift_ms -= step_ms

    def _maybe_apply_runtime_input_drift(self, lead_error_ms: float) -> None:
        assert self._state is not None

        if self._reliable_sync_hits < (self.min_sync_hits_before_update + 4):
            return
        if abs(lead_error_ms) < 170.0:
            return

        bounded_error_ms = max(-200.0, min(200.0, float(lead_error_ms)))
        direction = 1.0 if bounded_error_ms > 0.0 else -1.0
        step_ms = min(self.input_latency_adapt_ms, max(0.6, abs(bounded_error_ms) * 0.018))
        self._state.runtime_input_drift_ms += direction * step_ms

    def _clamp_runtime_drifts(self) -> None:
        assert self._state is not None
        self._state.runtime_output_drift_ms = max(
            -self.max_runtime_output_drift_ms,
            min(self.max_runtime_output_drift_ms, self._state.runtime_output_drift_ms),
        )
        self._state.runtime_input_drift_ms = max(
            -self.max_runtime_input_drift_ms,
            min(self.max_runtime_input_drift_ms, self._state.runtime_input_drift_ms),
        )

    def _soft_reset_observation_run(self) -> None:
        self._reliable_sync_hits = 0
        self._last_reliable_error_ms = None