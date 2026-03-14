from __future__ import annotations

from bisect import bisect_right

import numpy as np

from shadowing.types import AudioChunk


class ChunkQueue:
    def __init__(self) -> None:
        self._chunks: list[AudioChunk] = []
        self._chunk_start_times: list[float] = []
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = 0
        self._total_duration_sec = 0.0

    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._chunk_start_times = [c.start_time_sec for c in chunks]
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = chunks[0].sample_rate if chunks else 0
        if chunks and any(c.sample_rate != self._sample_rate for c in chunks):
            raise ValueError("All playback chunks must share the same sample rate.")
        if chunks:
            last = chunks[-1]
            self._total_duration_sec = last.start_time_sec + last.duration_sec
        else:
            self._total_duration_sec = 0.0

    @property
    def current_chunk_id(self) -> int:
        if not self._chunks:
            return -1
        if self._current_chunk_idx >= len(self._chunks):
            return self._chunks[-1].chunk_id
        return self._chunks[self._current_chunk_idx].chunk_id

    @property
    def current_frame_index(self) -> int:
        return self._frame_offset_in_chunk

    def is_finished(self) -> bool:
        return bool(self._chunks) and self._current_chunk_idx >= len(self._chunks)

    def seek(self, target_time_sec: float) -> None:
        if not self._chunks:
            return
        idx = bisect_right(self._chunk_start_times, target_time_sec) - 1
        idx = max(0, min(idx, len(self._chunks) - 1))
        chunk = self._chunks[idx]
        local_time = max(0.0, target_time_sec - chunk.start_time_sec)
        local_frame = int(local_time * chunk.sample_rate)
        local_frame = min(local_frame, chunk.samples.shape[0])
        self._current_chunk_idx = idx
        self._frame_offset_in_chunk = local_frame

    def get_content_time_sec(self) -> float:
        if not self._chunks:
            return 0.0
        if self._current_chunk_idx >= len(self._chunks):
            return self._total_duration_sec
        chunk = self._chunks[self._current_chunk_idx]
        return chunk.start_time_sec + (self._frame_offset_in_chunk / chunk.sample_rate)

    def read_frames(self, frames: int, channels: int = 1) -> np.ndarray:
        out = np.zeros((frames, channels), dtype=np.float32)
        if not self._chunks or self.is_finished():
            return out
        written = 0
        while written < frames and self._current_chunk_idx < len(self._chunks):
            chunk = self._chunks[self._current_chunk_idx]
            remain = chunk.samples.shape[0] - self._frame_offset_in_chunk
            take = min(remain, frames - written)
            if take > 0:
                data = chunk.samples[self._frame_offset_in_chunk : self._frame_offset_in_chunk + take]
                if data.ndim == 1:
                    out[written : written + take, 0] = data
                else:
                    out[written : written + take, : data.shape[1]] = data
                self._frame_offset_in_chunk += take
                written += take
            if self._frame_offset_in_chunk >= chunk.samples.shape[0]:
                self._current_chunk_idx += 1
                self._frame_offset_in_chunk = 0
        return out