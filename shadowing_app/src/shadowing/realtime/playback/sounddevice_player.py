from __future__ import annotations

import sounddevice as sd

from shadowing.interfaces.player import Player
from shadowing.types import (
    AudioChunk,
    PlaybackState,
    PlaybackStatus,
    PlayerCommand,
    PlayerCommandType,
)
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock
from shadowing.realtime.playback.command_slot import CommandSlot


class SoundDevicePlayer(Player):
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        device: int | None = None,
        bluetooth_output_offset_sec: float = 0.0,
        latency: str | float = "low",
        blocksize: int = 0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.latency = latency
        self.blocksize = blocksize

        self.clock = PlaybackClock(bluetooth_output_offset_sec)
        self.queue = ChunkQueue()
        self.command_slot = CommandSlot()

        self._stream: sd.OutputStream | None = None
        self._state = PlaybackState.STOPPED

        self._current_chunk_id = -1
        self._frame_index = 0
        self._t_host_output_sec = 0.0
        self._t_ref_sched_sec = 0.0
        self._t_ref_heard_sec = 0.0

        self._gain = 1.0

    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        self.queue.load(chunks)
        if chunks:
            self._current_chunk_id = chunks[0].chunk_id
            self._frame_index = 0

    def start(self) -> None:
        if self._stream is not None:
            return

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._audio_callback,
            device=self.device,
            latency=self.latency,
            blocksize=self.blocksize,
        )
        self._stream.start()
        self._state = PlaybackState.PLAYING

    def submit_command(self, command: PlayerCommand) -> None:
        self.command_slot.put(command)

    def get_status(self) -> PlaybackStatus:
        return PlaybackStatus(
            state=self._state,
            chunk_id=self._current_chunk_id,
            frame_index=self._frame_index,
            t_host_output_sec=self._t_host_output_sec,
            t_ref_sched_sec=self._t_ref_sched_sec,
            t_ref_heard_sec=self._t_ref_heard_sec,
        )

    def stop(self) -> None:
        self.submit_command(PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop"))

    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED

    def _apply_command_if_any(self) -> None:
        cmd = self.command_slot.pop()
        if cmd is None:
            return

        if cmd.cmd == PlayerCommandType.HOLD:
            self._state = PlaybackState.HOLDING

        elif cmd.cmd == PlayerCommandType.RESUME:
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.SEEK:
            self._state = PlaybackState.SEEKING
            if cmd.target_time_sec is not None:
                self.queue.seek(cmd.target_time_sec)
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.STOP:
            self._state = PlaybackState.STOPPED

        elif cmd.cmd == PlayerCommandType.START:
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.SET_GAIN:
            if cmd.gain is not None:
                self._gain = min(max(cmd.gain, 0.0), 1.0)

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        self._apply_command_if_any()

        if self._state in (PlaybackState.STOPPED, PlaybackState.HOLDING, PlaybackState.FINISHED):
            outdata.fill(0.0)
        else:
            block = self.queue.read_frames(frames=frames, channels=self.channels)

            # 关键补丁：ducking / gain control
            outdata[:] = block * self._gain

            if self.queue.is_finished():
                self._state = PlaybackState.FINISHED

            self._current_chunk_id = self.queue.current_chunk_id
            self._frame_index = self.queue.current_frame_index

        scheduled_ref_time = self.queue.get_scheduled_time_sec()
        clock_snapshot = self.clock.compute(
            output_buffer_dac_time_sec=time_info.outputBufferDacTime,
            scheduled_ref_time_sec=scheduled_ref_time,
        )
        self._t_host_output_sec = clock_snapshot.t_host_output_sec
        self._t_ref_sched_sec = clock_snapshot.t_ref_sched_sec
        self._t_ref_heard_sec = clock_snapshot.t_ref_heard_sec