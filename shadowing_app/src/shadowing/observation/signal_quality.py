from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shadowing.types import SignalQuality


@dataclass(slots=True)
class _SignalState:
    last_observed_at_sec: float = 0.0
    last_rms: float = 0.0
    last_peak: float = 0.0
    noise_floor_rms: float = 0.0025
    speaking_likelihood: float = 0.0
    last_active_at_sec: float = 0.0
    clipping_ratio: float = 0.0
    dropout_detected: bool = False


class SignalQualityMonitor:
    def __init__(
        self,
        min_vad_rms: float = 0.006,
        vad_noise_multiplier: float = 2.8,
        speaking_decay: float = 0.92,
        speaking_rise: float = 0.22,
        clipping_threshold: float = 0.98,
    ) -> None:
        self.min_vad_rms = float(min_vad_rms)
        self.vad_noise_multiplier = float(vad_noise_multiplier)
        self.speaking_decay = float(speaking_decay)
        self.speaking_rise = float(speaking_rise)
        self.clipping_threshold = float(clipping_threshold)
        self.state = _SignalState()

    def feed_pcm16(self, pcm_bytes: bytes, observed_at_sec: float) -> None:
        if not pcm_bytes:
            return

        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return

        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_f32)))) if audio_f32.size else 0.0
        peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
        clipping_ratio = float(np.mean(np.abs(audio_f32) >= self.clipping_threshold)) if audio_f32.size else 0.0

        noise_floor = self.state.noise_floor_rms
        dynamic_threshold = max(self.min_vad_rms, noise_floor * self.vad_noise_multiplier)
        vad_active = rms >= dynamic_threshold and peak >= max(0.012, dynamic_threshold * 1.2)

        if vad_active:
            self.state.last_active_at_sec = observed_at_sec
            self.state.speaking_likelihood = min(
                1.0,
                self.state.speaking_likelihood * self.speaking_decay + self.speaking_rise + 0.10,
            )
        else:
            self.state.speaking_likelihood *= self.speaking_decay

        if rms < max(self.min_vad_rms * 0.7, dynamic_threshold * 0.8):
            self.state.noise_floor_rms = 0.96 * noise_floor + 0.04 * rms
        else:
            self.state.noise_floor_rms = 0.995 * noise_floor + 0.005 * rms

        self.state.last_observed_at_sec = observed_at_sec
        self.state.last_rms = rms
        self.state.last_peak = peak
        self.state.clipping_ratio = clipping_ratio
        self.state.dropout_detected = rms <= 1e-5 and peak <= 1e-5

    def snapshot(self, now_sec: float) -> SignalQuality:
        last_seen = self.state.last_observed_at_sec
        silence_run = 9999.0 if self.state.last_active_at_sec <= 0.0 else max(
            0.0,
            now_sec - self.state.last_active_at_sec,
        )

        freshness_penalty = 0.0
        if last_seen > 0.0:
            freshness_penalty = min(0.35, max(0.0, now_sec - last_seen) * 0.30)

        base_quality = 0.50
        base_quality += min(0.20, self.state.last_peak * 0.6)
        base_quality += min(0.15, self.state.speaking_likelihood * 0.20)
        base_quality -= min(0.18, self.state.clipping_ratio * 2.0)
        base_quality -= freshness_penalty
        if self.state.dropout_detected:
            base_quality -= 0.20

        dynamic_threshold = max(self.min_vad_rms, self.state.noise_floor_rms * self.vad_noise_multiplier)
        vad_active = self.state.last_rms >= dynamic_threshold and self.state.last_peak >= max(
            0.012,
            dynamic_threshold * 1.2,
        )

        return SignalQuality(
            observed_at_sec=float(last_seen),
            rms=float(self.state.last_rms),
            peak=float(self.state.last_peak),
            vad_active=bool(vad_active),
            speaking_likelihood=float(max(0.0, min(1.0, self.state.speaking_likelihood))),
            silence_run_sec=float(silence_run),
            clipping_ratio=float(self.state.clipping_ratio),
            dropout_detected=bool(self.state.dropout_detected),
            quality_score=float(max(0.0, min(1.0, base_quality))),
        )