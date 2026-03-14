from __future__ import annotations

from shadowing.types import RefToken, ReferenceMap


class WindowSelector:
    def __init__(self, look_back: int = 8, look_ahead: int = 40) -> None:
        self.look_back = int(look_back)
        self.look_ahead = int(look_ahead)

    def select(
        self,
        ref_map: ReferenceMap,
        committed_idx: int,
        *,
        look_back: int | None = None,
        look_ahead: int | None = None,
    ) -> tuple[list[RefToken], int, int]:
        back = self.look_back if look_back is None else max(1, int(look_back))
        ahead = self.look_ahead if look_ahead is None else max(1, int(look_ahead))
        start = max(0, committed_idx - back)
        end = min(len(ref_map.tokens), committed_idx + ahead + 1)
        return ref_map.tokens[start:end], start, end