from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import RawAsrEvent


class ASRProvider(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def feed_pcm16(self, pcm_bytes: bytes) -> None: ...

    @abstractmethod
    def poll_raw_events(self) -> list[RawAsrEvent]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...