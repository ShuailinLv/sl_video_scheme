from __future__ import annotations

from collections.abc import Callable

import numpy as np
import sounddevice as sd

from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler


class SoundDeviceRecorder(Recorder):
    """
    设计目标：
    1. 输入回调只做极轻处理
    2. 输出统一为 mono 16k PCM16 bytes（或 target_sample_rate）
    3. 不在 callback 中做阻塞操作
    """

    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | None = None,
        dtype: str = "float32",
        latency: str | float = "low",
        blocksize: int = 0,
    ) -> None:
        self.sample_rate_in = sample_rate_in
        self.target_sample_rate = target_sample_rate
        self.channels = channels
        self.device = device
        self.dtype = dtype
        self.latency = latency
        self.blocksize = blocksize

        self._stream: sd.InputStream | None = None
        self._on_audio_frame: Callable[[bytes], None] | None = None
        self._resampler = AudioResampler(sample_rate_in, target_sample_rate)

        self._running = False
        self._overflow_count = 0

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._stream is not None:
            return

        self._on_audio_frame = on_audio_frame

        self._stream = sd.InputStream(
            samplerate=self.sample_rate_in,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._audio_callback,
            device=self.device,
            latency=self.latency,
            blocksize=self.blocksize,
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()

    def close(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """
        实时音频线程：
        - 不阻塞
        - 不做日志/磁盘/网络
        - 尽量只做轻量 numpy 处理 + 回调转发
        """
        if not self._running or self._on_audio_frame is None:
            return

        if status.input_overflow:
            self._overflow_count += 1

        # indata shape: (frames, channels)
        if self.channels == 1:
            mono = indata[:, 0]
        else:
            # 多通道时先简单平均成 mono
            mono = np.mean(indata, axis=1, dtype=np.float32)

        pcm_bytes = self._resampler.process_float_mono(mono)
        self._on_audio_frame(pcm_bytes)