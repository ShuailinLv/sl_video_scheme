from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import AudioChunk, PlaybackStatus, PlayerCommand


class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def submit_command(self, command: PlayerCommand) -> None: ...

    @abstractmethod
    def get_status(self) -> PlaybackStatus: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...