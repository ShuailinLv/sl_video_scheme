from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AudioChunk, PlaybackStatus


class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def hold(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def resume(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def seek(self, target_time_sec: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> PlaybackStatus:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError