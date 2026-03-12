from __future__ import annotations

from collections.abc import Callable
from shadowing.interfaces.recorder import Recorder


class SoundDeviceRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | None = None,
    ) -> None:
        self.sample_rate_in = sample_rate_in
        self.target_sample_rate = target_sample_rate
        self.channels = channels
        self.device = device
        self._on_audio_frame: Callable[[bytes], None] | None = None

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        self._on_audio_frame = on_audio_frame
        # TODO: 打开 sounddevice.InputStream
        # 如设备不是 16k，在这里重采样到 16k mono
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError