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
        target_shadow_lead_sec: float = 0.15,
        min_update_interval_sec: float = 1.0,
        min_tracking_quality: float = 0.84,
    ) -> None:
        self.target_shadow_lead_sec = float(target_shadow_lead_sec)
        self.min_update_interval_sec = float(min_update_interval_sec)
        self.min_tracking_quality = float(min_tracking_quality)

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._last_update_at_sec = 0.0
        self._obs_error_ema_ms = 0.0
        self._obs_consistency_run = 0

        self._max_observation_error_ms = 900.0
        self._min_error_ms_to_adjust = 32.0
        self._max_runtime_output_drift_ms = 90.0
        self._max_runtime_input_drift_ms = 60.0

        self._bluetooth_mode = False
        self._bluetooth_long_session_mode = False
        self._startup_fast_calibration_until_sec = 0.0

    def reset(
        self,
        device_profile: DeviceProfile,
        bluetooth_mode: bool = False,
        bluetooth_long_session_mode: bool = False,
        now_sec: float = 0.0,
    ) -> None:
        self._bluetooth_mode = bool(bluetooth_mode)
        self._bluetooth_long_session_mode = bool(bluetooth_long_session_mode)

        base_target_lead_sec = 0.15
        if self._bluetooth_mode:
            base_target_lead_sec = 0.35 if self._bluetooth_long_session_mode else 0.28
        self.target_shadow_lead_sec = float(base_target_lead_sec)

        self.min_update_interval_sec = 0.55 if self._bluetooth_mode else 1.0
        self.min_tracking_quality = 0.74 if self._bluetooth_mode else 0.84

        self._min_error_ms_to_adjust = 22.0 if self._bluetooth_mode else 32.0
        self._max_runtime_output_drift_ms = 180.0 if self._bluetooth_mode else 90.0
        self._max_runtime_input_drift_ms = 70.0 if self._bluetooth_mode else 60.0
        self._startup_fast_calibration_until_sec = float(now_sec) + (18.0 if self._bluetooth_mode else 0.0)

        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            runtime_input_drift_ms=0.0,
            runtime_output_drift_ms=0.0,
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._last_update_at_sec = 0.0
        self._obs_error_ema_ms = 0.0
        self._obs_consistency_run = 0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.52:
            self._last_active_at_sec = float(signal_quality.observed_at_sec)

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

    def corrected_playback_ref_time_sec(self, playback_ref_time_sec: float) -> float:
        input_ms = self.effective_input_latency_ms() or 0.0
        return float(playback_ref_time_sec) - max(0.0, input_ms / 1000.0)

    def observe_sync(
        self,
        *,
        playback_ref_time_sec: float,
        user_ref_time_sec: float,
        tracking_quality: float,
        stable: bool,
        active_speaking: bool,
        allow_observation: bool = True,
        source_is_text_dominant: bool = True,
        source_mode: str | None = None,
        audio_text_disagreement_sec: float | None = None,
    ) -> None:
        if self._state is None:
            return

        now_sec = max(float(playback_ref_time_sec), float(user_ref_time_sec))

        if not allow_observation:
            self._reset_observation_run(decay_only=True)
            return
        if not stable or tracking_quality < self.min_tracking_quality or not active_speaking:
            self._reset_observation_run(decay_only=True)
            return
        if self._last_active_at_sec <= 0.0 or (now_sec - self._last_active_at_sec) > 1.05:
            self._reset_observation_run(decay_only=True)
            return

        mode = str(source_mode or ("text" if source_is_text_dominant else "joint")).strip().lower()
        if mode not in {"text", "joint", "audio"}:
            mode = "text"

        if mode == "audio":
            source_weight = 0.40
        elif mode == "joint":
            source_weight = 0.70
        else:
            source_weight = 1.00

        if mode == "audio" and not self._bluetooth_mode:
            self._reset_observation_run(decay_only=True)
            return

        if audio_text_disagreement_sec is not None:
            max_allowed = 0.70 if self._bluetooth_mode else 0.55
            if abs(float(audio_text_disagreement_sec)) > max_allowed:
                self._reset_observation_run(decay_only=True)
                return

        if self._last_update_at_sec > 0.0 and (now_sec - self._last_update_at_sec) < self.min_update_interval_sec:
            self._increase_confidence(0.006, max_conf=0.86)
            return

        corrected_playback_ref = self.corrected_playback_ref_time_sec(playback_ref_time_sec)
        lead_sec = float(corrected_playback_ref) - float(user_ref_time_sec)
        error_ms = (lead_sec - self.target_shadow_lead_sec) * 1000.0
        error_ms *= source_weight

        if abs(error_ms) > self._max_observation_error_ms:
            self._reset_observation_run(decay_only=True)
            return

        self._accumulate_observation(error_ms)
        self._increase_confidence(0.012, max_conf=0.80 if self._bluetooth_mode else 0.78)

        required_consistency = 2 if (self._bluetooth_mode and now_sec <= self._startup_fast_calibration_until_sec) else 3
        if self._obs_consistency_run < required_consistency:
            return

        if abs(self._obs_error_ema_ms) < self._min_error_ms_to_adjust:
            self._increase_confidence(0.020, max_conf=0.94 if self._bluetooth_mode else 0.92)
            self._last_update_at_sec = now_sec
            return

        self._apply_correction(self._obs_error_ema_ms, now_sec=now_sec)
        self._last_update_at_sec = now_sec
        self._increase_confidence(0.030, max_conf=0.97 if self._bluetooth_mode else 0.96)

    def _accumulate_observation(self, error_ms: float) -> None:
        error_ms = float(max(-320.0, min(320.0, error_ms)))
        if self._obs_consistency_run <= 0:
            self._obs_error_ema_ms = error_ms
            self._obs_consistency_run = 1
            return

        tolerance = 90.0 if self._bluetooth_mode else 70.0
        if abs(error_ms - self._obs_error_ema_ms) <= tolerance:
            self._obs_consistency_run += 1
        else:
            self._obs_consistency_run = max(1, self._obs_consistency_run - 1)

        alpha = 0.28 if self._bluetooth_mode else 0.22
        self._obs_error_ema_ms = (1.0 - alpha) * self._obs_error_ema_ms + alpha * error_ms

    def _apply_correction(self, error_ms: float, now_sec: float) -> None:
        assert self._state is not None

        bounded = float(max(-260.0, min(260.0, error_ms)))
        magnitude = abs(bounded)
        sign = 1.0 if bounded > 0.0 else -1.0

        fast_startup = self._bluetooth_mode and now_sec <= self._startup_fast_calibration_until_sec

        if self._bluetooth_mode:
            if fast_startup:
                output_step = max(4.0, min(14.0, magnitude * 0.080))
                input_step = max(0.4, min(2.2, magnitude * 0.010))
            else:
                output_step = max(3.0, min(12.0, magnitude * 0.055))
                input_step = max(0.3, min(1.6, magnitude * 0.006))
        else:
            output_step = max(1.0, min(5.0, magnitude * 0.040))
            input_step = max(0.5, min(2.2, magnitude * 0.016))

        # 蓝牙场景下优先修输出侧，输入只做很小修正
        self._state.runtime_output_drift_ms += sign * output_step
        self._state.runtime_input_drift_ms += sign * input_step

        self._state.runtime_output_drift_ms = max(
            -self._max_runtime_output_drift_ms,
            min(self._max_runtime_output_drift_ms, self._state.runtime_output_drift_ms),
        )
        self._state.runtime_input_drift_ms = max(
            -self._max_runtime_input_drift_ms,
            min(self._max_runtime_input_drift_ms, self._state.runtime_input_drift_ms),
        )

        self._obs_consistency_run = max(1, self._obs_consistency_run - 1)

    def _increase_confidence(self, delta: float, *, max_conf: float) -> None:
        assert self._state is not None
        self._state.confidence = min(float(max_conf), self._state.confidence + float(delta))
        self._state.calibrated = self._state.confidence >= 0.60

    def _reset_observation_run(self, *, decay_only: bool) -> None:
        if decay_only:
            self._obs_consistency_run = max(0, self._obs_consistency_run - 1)
            self._obs_error_ema_ms *= 0.84 if self._bluetooth_mode else 0.80
        else:
            self._obs_consistency_run = 0
            self._obs_error_ema_ms = 0.0