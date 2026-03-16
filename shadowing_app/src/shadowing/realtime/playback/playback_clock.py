from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackClockSnapshot:
    t_host_output_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_heard_content_sec: float


class PlaybackClock:
    def __init__(self, bluetooth_output_offset_sec: float = 0.0) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(bluetooth_output_offset_sec))
        self._last_emitted_content_sec = 0.0
        self._last_heard_content_sec = 0.0
        self._last_host_output_sec = 0.0

    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(offset_sec))

    def compute(
        self,
        output_buffer_dac_time_sec: float,
        block_start_content_sec: float,
        block_end_content_sec: float,
    ) -> PlaybackClockSnapshot:
        start_sec = float(block_start_content_sec)
        end_sec = float(block_end_content_sec)
        if end_sec < start_sec:
            end_sec = start_sec

        # 关键改动：
        # 不再把 emitted 简化成 block_start，而是用 block 中点作为“当前块代表时刻”。
        # 这样控制层拿到的参考播放时间更接近连续时钟，而不是块状跳变。
        emitted_mid_sec = (start_sec + end_sec) * 0.5

        # heard 仍然以输出偏置补偿为主，但作用到 block 中点上。
        heard_mid_sec = emitted_mid_sec + self.bluetooth_output_offset_sec

        # 单调保护，避免由于 seek/回调抖动造成的回退噪声
        if output_buffer_dac_time_sec >= self._last_host_output_sec:
            emitted_mid_sec = max(emitted_mid_sec, self._last_emitted_content_sec)
            heard_mid_sec = max(heard_mid_sec, self._last_heard_content_sec)

        self._last_host_output_sec = float(output_buffer_dac_time_sec)
        self._last_emitted_content_sec = float(emitted_mid_sec)
        self._last_heard_content_sec = float(heard_mid_sec)

        return PlaybackClockSnapshot(
            t_host_output_sec=float(output_buffer_dac_time_sec),
            t_ref_block_start_content_sec=start_sec,
            t_ref_block_end_content_sec=end_sec,
            t_ref_emitted_content_sec=float(emitted_mid_sec),
            t_ref_heard_content_sec=float(heard_mid_sec),
        )