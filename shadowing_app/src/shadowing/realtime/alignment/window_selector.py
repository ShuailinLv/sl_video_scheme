from __future__ import annotations

from shadowing.types import ReferenceMap, RefToken


class WindowSelector:
    def __init__(self, look_back: int = 3, look_ahead: int = 18) -> None:
        self.look_back = look_back
        self.look_ahead = look_ahead

    def select(self, ref_map: ReferenceMap, committed_idx: int) -> tuple[list[RefToken], int, int]:
        start = max(0, committed_idx - self.look_back)
        end = min(len(ref_map.tokens), committed_idx + self.look_ahead)
        return ref_map.tokens[start:end], start, end