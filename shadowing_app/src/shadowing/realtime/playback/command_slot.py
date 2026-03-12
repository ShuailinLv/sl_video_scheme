from __future__ import annotations

from shadowing.types import PlayerCommand


class CommandSlot:
    def __init__(self) -> None:
        self._cmd: PlayerCommand | None = None

    def put(self, cmd: PlayerCommand) -> None:
        self._cmd = cmd

    def pop(self) -> PlayerCommand | None:
        cmd = self._cmd
        self._cmd = None
        return cmd