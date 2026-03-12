from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackClockSnapshot:
    t_host_output_sec: float
    t_ref_sched_sec: float
    t_ref_heard_sec: float


class PlaybackClock:
    def __init__(self, bluetooth_output_offset_sec: float = 0.0) -> None:
        self.bluetooth_output_offset_sec = bluetooth_output_offset_sec

    def compute(
        self,
        output_buffer_dac_time_sec: float,
        scheduled_ref_time_sec: float,
    ) -> PlaybackClockSnapshot:
        heard = scheduled_ref_time_sec - self.bluetooth_output_offset_sec
        return PlaybackClockSnapshot(
            t_host_output_sec=output_buffer_dac_time_sec,
            t_ref_sched_sec=scheduled_ref_time_sec,
            t_ref_heard_sec=max(0.0, heard),
        )