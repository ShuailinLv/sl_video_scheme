from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly


class AudioResampler:
    """
    将 float32/float64 mono 音频重采样，并输出 int16 PCM bytes。
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = src_rate
        self.dst_rate = dst_rate

        g = gcd(src_rate, dst_rate)
        self.up = dst_rate // g
        self.down = src_rate // g

    def float_to_pcm16_bytes(self, audio: np.ndarray) -> bytes:
        """
        输入:
            audio: shape=(n,) float32/64, 期望范围 [-1, 1]
        输出:
            little-endian int16 PCM bytes
        """
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")

        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = (clipped * 32767.0).astype(np.int16)
        return pcm16.tobytes()

    def process_float_mono(self, audio: np.ndarray) -> bytes:
        """
        输入任意长度 mono float，输出 dst_rate 的 int16 PCM bytes
        """
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")

        if self.src_rate == self.dst_rate:
            return self.float_to_pcm16_bytes(audio)

        y = resample_poly(audio, self.up, self.down)
        y = y.astype(np.float32, copy=False)
        return self.float_to_pcm16_bytes(y)