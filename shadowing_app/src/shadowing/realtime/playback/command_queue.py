from __future__ import annotations

import queue
from dataclasses import dataclass

from shadowing.types import PlayerCommand, PlayerCommandType


@dataclass(slots=True)
class MergedPlayerCommands:
    state_cmd: PlayerCommand | None = None
    seek_cmd: PlayerCommand | None = None
    gain_cmd: PlayerCommand | None = None


class PlayerCommandQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._queue: queue.Queue[PlayerCommand] = queue.Queue(maxsize=maxsize)

    def put(self, cmd: PlayerCommand) -> None:
        try:
            self._queue.put_nowait(cmd)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(cmd)

    def drain_merged(self) -> MergedPlayerCommands:
        merged = MergedPlayerCommands()
        while True:
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                break

            if cmd.cmd == PlayerCommandType.SET_GAIN:
                merged.gain_cmd = cmd
                continue

            if cmd.cmd == PlayerCommandType.SEEK:
                merged.seek_cmd = cmd
                continue

            if cmd.cmd == PlayerCommandType.STOP:
                merged.state_cmd = cmd
                continue

            if merged.state_cmd is None or merged.state_cmd.cmd != PlayerCommandType.STOP:
                merged.state_cmd = cmd

        return merged