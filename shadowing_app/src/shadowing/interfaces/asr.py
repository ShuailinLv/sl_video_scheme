from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AsrEvent


class ASRProvider(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def poll_events(self) -> list[AsrEvent]:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError