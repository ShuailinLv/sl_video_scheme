from __future__ import annotations

import threading
from shadowing.interfaces.player import Player
from shadowing.types import AudioChunk, PlaybackState, PlaybackStatus
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock


class SoundDevicePlayer(Player):
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        device: int | None = None,
        bluetooth_output_offset_sec: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.clock = PlaybackClock(bluetooth_output_offset_sec)
        self.queue = ChunkQueue()

        self._state = PlaybackState.STOPPED
        self._lock = threading.Lock()

        self._current_chunk_id = 0
        self._frame_index = 0
        self._t_host_output_sec = 0.0
        self._t_ref_sched_sec = 0.0
        self._t_ref_heard_sec = 0.0

        self._pending_seek_sec: float | None = None

    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        self.queue.load(chunks)

    def start(self) -> None:
        # TODO: 初始化 sounddevice.OutputStream，并 start
        self._state = PlaybackState.PLAYING

    def hold(self) -> None:
        with self._lock:
            self._state = PlaybackState.HOLDING

    def resume(self) -> None:
        with self._lock:
            self._state = PlaybackState.PLAYING

    def seek(self, target_time_sec: float) -> None:
        with self._lock:
            self._pending_seek_sec = target_time_sec
            self._state = PlaybackState.SEEKING

    def get_status(self) -> PlaybackStatus:
        return PlaybackStatus(
            state=self._state,
            chunk_id=self._current_chunk_id,
            frame_index=self._frame_index,
            t_host_output_sec=self._t_host_output_sec,
            t_ref_sched_sec=self._t_ref_sched_sec,
            t_ref_heard_sec=self._t_ref_heard_sec,
        )

    def stop(self) -> None:
        self._state = PlaybackState.STOPPED

    def close(self) -> None:
        # TODO: 关闭 stream
        self._state = PlaybackState.STOPPED

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        """
        这里只能做：
        - 取样本
        - 填 outdata
        - 更新时钟
        不做日志/网络/复杂逻辑
        """
        raise NotImplementedError