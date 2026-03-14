from __future__ import annotations

from shadowing.types import RefToken, ReferenceMap


class WindowSelector:
    def __init__(self, look_back: int = 8, look_ahead: int = 40) -> None:
        self.look_back = int(look_back)
        self.look_ahead = int(look_ahead)

    def select(self, ref_map: ReferenceMap, committed_idx: int) -> tuple[list[RefToken], int, int]:
        start = max(0, committed_idx - self.look_back)
        end = min(len(ref_map.tokens), committed_idx + self.look_ahead + 1)
        return ref_map.tokens[start:end], start, end