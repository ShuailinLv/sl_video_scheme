from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class Recorder(ABC):
    @abstractmethod
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError