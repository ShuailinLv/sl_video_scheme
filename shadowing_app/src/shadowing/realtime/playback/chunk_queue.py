from __future__ import annotations

from shadowing.types import AudioChunk


class ChunkQueue:
    def __init__(self) -> None:
        self._chunks: list[AudioChunk] = []
        self._current_chunk_idx: int = 0
        self._frame_offset_in_chunk: int = 0

    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0

    def seek(self, target_time_sec: float) -> None:
        # TODO: 把绝对时间映射到 chunk_id + frame_offset
        raise NotImplementedError

    def read_frames(self, frames: int):
        # TODO: 返回连续 frames 的 numpy 数据
        raise NotImplementedError