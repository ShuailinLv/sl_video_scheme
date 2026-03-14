from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly


class AudioResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g

    def float_to_pcm16_bytes(self, audio: np.ndarray) -> bytes:
        clipped = np.clip(audio, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()

    def process_float_mono(self, audio: np.ndarray) -> bytes:
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")
        if self.src_rate == self.dst_rate:
            return self.float_to_pcm16_bytes(audio)
        y = resample_poly(audio, self.up, self.down).astype(np.float32, copy=False)
        return self.float_to_pcm16_bytes(y)