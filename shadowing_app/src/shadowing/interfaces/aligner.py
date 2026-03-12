from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AsrEvent, AlignResult, ReferenceMap


class Aligner(ABC):
    @abstractmethod
    def reset(self, reference_map: ReferenceMap) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(self, event: AsrEvent) -> AlignResult | None:
        raise NotImplementedError