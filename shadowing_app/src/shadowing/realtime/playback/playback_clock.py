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
        self.bluetooth_output_offset_sec = float(bluetooth_output_offset_sec)

    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(offset_sec))

    def compute(
        self,
        output_buffer_dac_time_sec: float,
        block_start_content_sec: float,
        block_end_content_sec: float,
    ) -> PlaybackClockSnapshot:
        emitted = block_start_content_sec
        heard = max(0.0, emitted - self.bluetooth_output_offset_sec)
        return PlaybackClockSnapshot(
            t_host_output_sec=float(output_buffer_dac_time_sec),
            t_ref_block_start_content_sec=float(block_start_content_sec),
            t_ref_block_end_content_sec=float(block_end_content_sec),
            t_ref_emitted_content_sec=float(emitted),
            t_ref_heard_content_sec=float(heard),
        )