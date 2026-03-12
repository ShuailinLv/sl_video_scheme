from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AudioChunk, PlaybackStatus, PlayerCommand


class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def submit_command(self, command: PlayerCommand) -> None:
        """
        非实时线程调用。
        只投递命令，不直接改 callback 内部状态。
        """
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