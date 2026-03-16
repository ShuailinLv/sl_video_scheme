from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass(slots=True)
class AudioFrameFeature:
    observed_at_sec: float
    envelope: float
    onset_strength: float
    voiced_ratio: float
    band_energy: list[float]
    embedding: list[float] = field(default_factory=list)


class FrameFeatureExtractor:
    def __init__(
        self,
        sample_rate: int,
        frame_size_sec: float = 0.025,
        hop_sec: float = 0.010,
        n_bands: int = 6,
        min_voiced_rms: float = 0.005,
        n_mels: int = 24,
        embedding_alpha: float = 0.35,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.frame_size_sec = float(frame_size_sec)
        self.hop_sec = float(hop_sec)
        self.n_bands = max(2, int(n_bands))
        self.min_voiced_rms = float(min_voiced_rms)
        self.n_mels = max(8, int(n_mels))
        self.embedding_alpha = float(max(0.0, min(1.0, embedding_alpha)))
        self.frame_size = max(16, int(round(self.sample_rate * self.frame_size_sec)))
        self.hop_size = max(8, int(round(self.sample_rate * self.hop_sec)))
        self._tail = np.zeros((0,), dtype=np.float32)
        self._last_envelope = 0.0
        self._last_log_mel = np.zeros((self.n_mels,), dtype=np.float32)

    def reset(self) -> None:
        self._tail = np.zeros((0,), dtype=np.float32)
        self._last_envelope = 0.0
        self._last_log_mel = np.zeros((self.n_mels,), dtype=np.float32)

    def process_pcm16(self, pcm_bytes: bytes, *, observed_at_sec: float) -> list[AudioFrameFeature]:
        if not pcm_bytes:
            return []
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return []
        audio_f32 = (audio_i16.astype(np.float32) / 32768.0).astype(np.float32, copy=False)
        start_time_sec = float(observed_at_sec) - (audio_f32.shape[0] / float(self.sample_rate))
        return self.process_float_audio(audio_f32, start_time_sec=start_time_sec)

    def process_float_audio(self, audio_f32: np.ndarray, *, start_time_sec: float) -> list[AudioFrameFeature]:
        arr = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return []
        full = np.concatenate([self._tail, arr], axis=0)
        out: list[AudioFrameFeature] = []
        pos = 0
        while pos + self.frame_size <= full.shape[0]:
            frame = full[pos : pos + self.frame_size]
            frame_time_sec = float(start_time_sec) + max(0, pos - self._tail.shape[0]) / float(self.sample_rate)
            out.append(self._extract_frame_feature(frame, frame_time_sec))
            pos += self.hop_size
        self._tail = full[pos:].astype(np.float32, copy=False)
        max_tail = max(self.frame_size, self.hop_size) * 2
        if self._tail.shape[0] > max_tail:
            self._tail = self._tail[-max_tail:]
        return out

    def _extract_frame_feature(self, frame: np.ndarray, frame_time_sec: float) -> AudioFrameFeature:
        eps = 1e-8
        envelope = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        onset_strength = max(0.0, envelope - self._last_envelope)
        self._last_envelope = envelope
        abs_frame = np.abs(frame)
        voiced_ratio = float(np.mean(abs_frame >= max(self.min_voiced_rms, envelope * 0.55))) if frame.size else 0.0
        win = np.hanning(frame.shape[0]).astype(np.float32, copy=False)
        spec = np.abs(np.fft.rfft(frame * win))
        if spec.size <= 1:
            band_energy = [0.0] * self.n_bands
            log_mel = np.zeros((self.n_mels,), dtype=np.float32)
        else:
            band_energy = self._compute_band_energy(spec)
            log_mel = self._compute_log_mel(spec)
        delta = log_mel - self._last_log_mel
        smoothed = (1.0 - self.embedding_alpha) * self._last_log_mel + self.embedding_alpha * log_mel
        self._last_log_mel = smoothed.astype(np.float32, copy=False)
        embedding = np.concatenate(
            [
                smoothed,
                delta,
                np.asarray([envelope, onset_strength, voiced_ratio], dtype=np.float32),
            ],
            axis=0,
        )
        norm = float(np.linalg.norm(embedding))
        if norm > 1e-6:
            embedding = embedding / norm
        return AudioFrameFeature(
            observed_at_sec=float(frame_time_sec),
            envelope=float(envelope),
            onset_strength=float(onset_strength),
            voiced_ratio=float(voiced_ratio),
            band_energy=band_energy,
            embedding=embedding.astype(np.float32, copy=False).tolist(),
        )

    def _compute_band_energy(self, spec: np.ndarray) -> list[float]:
        eps = 1e-8
        edges = np.linspace(0, spec.shape[0], self.n_bands + 1, dtype=int)
        band_energy: list[float] = []
        total = float(np.sum(spec) + eps)
        for i in range(self.n_bands):
            lo = int(edges[i])
            hi = int(edges[i + 1])
            if hi <= lo:
                band_energy.append(0.0)
            else:
                band_energy.append(float(np.sum(spec[lo:hi]) / total))
        return band_energy

    def _compute_log_mel(self, spec: np.ndarray) -> np.ndarray:
        power = np.square(np.asarray(spec, dtype=np.float32))
        n_bins = power.shape[0]
        edges = np.linspace(0, n_bins, self.n_mels + 1, dtype=int)
        mel = np.zeros((self.n_mels,), dtype=np.float32)
        for i in range(self.n_mels):
            lo = int(edges[i])
            hi = max(lo + 1, int(edges[i + 1]))
            mel[i] = float(np.mean(power[lo:hi]))
        mel = np.log1p(mel)
        mu = float(np.mean(mel))
        sigma = float(np.std(mel))
        if sigma > 1e-6:
            mel = (mel - mu) / sigma
        else:
            mel = mel - mu
        return mel.astype(np.float32, copy=False)
