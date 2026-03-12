from __future__ import annotations


class BluetoothOffsetCalibrator:
    """
    这里先只定义接口。
    初版可以手工配置 offset。
    二期再做自动校准流程。
    """

    def estimate_offset_sec(self) -> float:
        raise NotImplementedError