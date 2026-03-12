from __future__ import annotations

from shadowing.types import PlayerCommand


class CommandSlot:
    """
    单槽命令箱。
    外部线程 overwrite 最新命令，callback 线程取走并清空。

    目标：
    - 不在 callback 中等待
    - 不引入 queue.get() 之类阻塞操作
    - 对于高频控制，保留“最新命令”比积压历史命令更合理
    """

    def __init__(self) -> None:
        self._cmd: PlayerCommand | None = None

    def put(self, cmd: PlayerCommand) -> None:
        self._cmd = cmd

    def pop(self) -> PlayerCommand | None:
        cmd = self._cmd
        self._cmd = None
        return cmd