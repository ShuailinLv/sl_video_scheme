from __future__ import annotations

from dataclasses import dataclass
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

from shadowing.interfaces.player import Player
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.command_queue import PlayerCommandQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock
from shadowing.types import AudioChunk, PlaybackState, PlaybackStatus, PlayerCommand, PlayerCommandType


@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int
    device: int | None = None
    latency: str | float = "low"
    blocksize: int = 0
    bluetooth_output_offset_sec: float = 0.0


class _OutputResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g

    def process(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D audio array, got shape={arr.shape}")
        if self.src_rate == self.dst_rate or arr.shape[0] == 0:
            return arr.astype(np.float32, copy=False)

        channels = arr.shape[1]
        pieces: list[np.ndarray] = []
        for ch in range(channels):
            y = resample_poly(arr[:, ch], self.up, self.down).astype(np.float32, copy=False)
            pieces.append(y)

        min_len = min(piece.shape[0] for piece in pieces)
        if min_len <= 0:
            return np.zeros((0, channels), dtype=np.float32)

        out = np.stack([piece[:min_len] for piece in pieces], axis=1)
        return out.astype(np.float32, copy=False)


class SoundDevicePlayer(Player):
    def __init__(self, config: PlaybackConfig) -> None:
        self.config = config
        self.clock = PlaybackClock(config.bluetooth_output_offset_sec)
        self.queue = ChunkQueue()
        self.command_queue = PlayerCommandQueue()
        self._stream: sd.OutputStream | None = None
        self._state = PlaybackState.STOPPED
        self._gain = 1.0
        self._generation = 0
        self._callback_count = 0

        self._content_sample_rate = int(config.sample_rate)
        self._opened_output_sample_rate = int(config.sample_rate)
        self._output_resampler: _OutputResampler | None = None

        self._resolved_output_device: int | None = None
        self._resolved_output_device_name = ""
        self._silent_branch_logged = False

        self._status_snapshot = PlaybackStatus(
            state=PlaybackState.STOPPED,
            chunk_id=-1,
            frame_index=0,
            gain=1.0,
            generation=0,
            t_host_output_sec=0.0,
            t_ref_block_start_content_sec=0.0,
            t_ref_block_end_content_sec=0.0,
            t_ref_emitted_content_sec=0.0,
            t_ref_heard_content_sec=0.0,
        )

    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.clock.set_output_offset_sec(offset_sec)

    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        if chunks and any(c.sample_rate != self.config.sample_rate for c in chunks):
            raise ValueError("Chunk sample rate does not match player config sample rate.")
        self.queue.load(chunks)
        self._content_sample_rate = int(self.config.sample_rate)
        total_duration = chunks[-1].start_time_sec + chunks[-1].duration_sec if chunks else 0.0
        print(
            f"[PLAYER] loaded_chunks={len(chunks)} sample_rate={self.config.sample_rate} "
            f"channels={self.config.channels} total_duration_sec={total_duration:.3f}"
        )

    def start(self) -> None:
        if self._stream is not None:
            return

        actual_device = self._resolve_output_device(self.config.device)
        dev_info = sd.query_devices(actual_device, "output")

        opened_sr = self._pick_openable_output_samplerate(actual_device, dev_info)
        self._opened_output_sample_rate = int(opened_sr)
        self._output_resampler = (
            None
            if self._opened_output_sample_rate == self._content_sample_rate
            else _OutputResampler(
                src_rate=self._content_sample_rate,
                dst_rate=self._opened_output_sample_rate,
            )
        )

        self._resolved_output_device = int(actual_device)
        self._resolved_output_device_name = str(dev_info["name"])

        print(
            f"[PLAYER-START] requested_device={self.config.device} "
            f"resolved_device={self._resolved_output_device} "
            f"name={self._resolved_output_device_name} "
            f"latency={self.config.latency} blocksize={self.config.blocksize}"
        )

        try:
            self._stream = sd.OutputStream(
                samplerate=self._opened_output_sample_rate,
                channels=self.config.channels,
                dtype="float32",
                callback=self._audio_callback,
                device=self._resolved_output_device,
                latency=self.config.latency,
                blocksize=self.config.blocksize,
            )

            self._state = PlaybackState.PLAYING
            self._silent_branch_logged = False
            self._stream.start()

            print(
                f"[PLAYER] opened_output device={self._resolved_output_device} "
                f"name={dev_info['name']} default_sr={float(dev_info['default_samplerate'])} "
                f"content_sr={self._content_sample_rate} stream_sr={self._opened_output_sample_rate} "
                f"channels={self.config.channels}"
            )
            if self._opened_output_sample_rate != self._content_sample_rate:
                print(
                    f"[PLAYER] output_resample enabled "
                    f"{self._content_sample_rate} -> {self._opened_output_sample_rate}"
                )
        except Exception as e:
            self._state = PlaybackState.STOPPED
            raise RuntimeError(
                f"Failed to open output stream: device={self._resolved_output_device}, "
                f"sample_rate={self._opened_output_sample_rate}, channels={self.config.channels}, "
                f"latency={self.config.latency}, blocksize={self.config.blocksize}"
            ) from e

    def submit_command(self, command: PlayerCommand) -> None:
        self.command_queue.put(command)

    def get_status(self) -> PlaybackStatus:
        return self._status_snapshot

    def stop(self) -> None:
        self.submit_command(PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop"))

    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED

    def _apply_merged_commands(self) -> None:
        merged = self.command_queue.drain_merged()

        if merged.gain_cmd and merged.gain_cmd.gain is not None:
            self._gain = min(max(merged.gain_cmd.gain, 0.0), 1.0)

        hold_after_seek = False
        if merged.state_cmd is not None:
            if merged.state_cmd.cmd == PlayerCommandType.HOLD:
                hold_after_seek = True
            elif merged.state_cmd.cmd == PlayerCommandType.RESUME:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False
            elif merged.state_cmd.cmd == PlayerCommandType.STOP:
                self._state = PlaybackState.STOPPED
            elif merged.state_cmd.cmd == PlayerCommandType.START:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False

        if merged.seek_cmd is not None and merged.seek_cmd.target_time_sec is not None:
            self._state = PlaybackState.SEEKING
            self.queue.seek(merged.seek_cmd.target_time_sec)
            self._generation += 1
            self._state = PlaybackState.HOLDING if hold_after_seek else PlaybackState.PLAYING
            if self._state == PlaybackState.PLAYING:
                self._silent_branch_logged = False
        elif hold_after_seek:
            self._state = PlaybackState.HOLDING

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        self._callback_count += 1
        self._apply_merged_commands()
        block_start = self.queue.get_content_time_sec()

        if self._state in (PlaybackState.STOPPED, PlaybackState.HOLDING, PlaybackState.FINISHED):
            outdata.fill(0.0)
            if not self._silent_branch_logged:
                print(
                    f"[PLAYER-SILENT] callback active but state={self._state.value} "
                    f"device={self._resolved_output_device} frames={frames}"
                )
                self._silent_branch_logged = True
        else:
            self._silent_branch_logged = False

            if self._output_resampler is None:
                block = self.queue.read_frames(frames=frames, channels=self.config.channels)
            else:
                src_frames = self._estimate_source_frames(frames)
                source_block = self.queue.read_frames(frames=src_frames, channels=self.config.channels)
                block = self._output_resampler.process(source_block)

                if block.shape[0] < frames:
                    padded = np.zeros((frames, self.config.channels), dtype=np.float32)
                    if block.shape[0] > 0:
                        padded[: block.shape[0], :] = block
                    block = padded
                elif block.shape[0] > frames:
                    block = block[:frames, :]

            outdata[:] = block * self._gain

            if self.queue.is_finished():
                self._state = PlaybackState.FINISHED

            if self._callback_count <= 5 or self._callback_count % 50 == 0:
                peak = float(np.max(np.abs(outdata))) if outdata.size else 0.0
                print(
                    f"[PLAYER-CB] n={self._callback_count} frames={frames} "
                    f"state={self._state.value} chunk_id={self.queue.current_chunk_id} "
                    f"frame_index={self.queue.current_frame_index} peak={peak:.6f}"
                )

        if status:
            print(f"[PLAYER-CB-STATUS] {status}")

        block_end = self.queue.get_content_time_sec()
        snapshot = self.clock.compute(
            output_buffer_dac_time_sec=time_info.outputBufferDacTime,
            block_start_content_sec=block_start,
            block_end_content_sec=block_end,
        )
        self._status_snapshot = PlaybackStatus(
            state=self._state,
            chunk_id=self.queue.current_chunk_id,
            frame_index=self.queue.current_frame_index,
            gain=self._gain,
            generation=self._generation,
            t_host_output_sec=snapshot.t_host_output_sec,
            t_ref_block_start_content_sec=snapshot.t_ref_block_start_content_sec,
            t_ref_block_end_content_sec=snapshot.t_ref_block_end_content_sec,
            t_ref_emitted_content_sec=snapshot.t_ref_emitted_content_sec,
            t_ref_heard_content_sec=snapshot.t_ref_heard_content_sec,
        )

        if self._callback_count <= 3 or self._callback_count % 200 == 0:
            peak_now = float(np.max(np.abs(outdata))) if outdata.size else 0.0
            print(
                f"[PLAYER-CB-HEARTBEAT] n={self._callback_count} "
                f"state={self._state.value} frames={frames} peak={peak_now:.6f}"
            )

    def _resolve_output_device(self, requested_device: int | None) -> int:
        if requested_device is not None:
            dev_info = sd.query_devices(requested_device)
            if int(dev_info["max_output_channels"]) <= 0:
                raise ValueError(
                    f"Requested device is not an output device: "
                    f"device={requested_device}, name={dev_info['name']}"
                )
            return int(requested_device)

        default_in, default_out = sd.default.device
        candidates: list[int] = []

        if default_out is not None and int(default_out) >= 0:
            candidates.append(int(default_out))
        if default_in is not None and int(default_in) >= 0 and int(default_in) not in candidates:
            candidates.append(int(default_in))

        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_output_channels"]) > 0 and idx not in candidates:
                candidates.append(idx)

        for idx in candidates:
            try:
                dev_info = sd.query_devices(idx)
                if int(dev_info["max_output_channels"]) > 0:
                    return int(idx)
            except Exception:
                continue

        raise RuntimeError("No valid output device available.")

    def _pick_openable_output_samplerate(self, device: int, dev_info) -> int:
        candidates: list[int] = []
        preferred = [
            self.config.sample_rate,
            int(float(dev_info["default_samplerate"])),
            48000,
            44100,
            16000,
        ]
        for sr in preferred:
            if sr > 0 and sr not in candidates:
                candidates.append(int(sr))

        last_error: Exception | None = None
        for sr in candidates:
            try:
                sd.check_output_settings(
                    device=device,
                    samplerate=sr,
                    channels=self.config.channels,
                    dtype="float32",
                )
                return int(sr)
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(
            f"Failed to find openable output samplerate for device={device}, "
            f"default_sr={float(dev_info['default_samplerate'])}, last_error={last_error}"
        )

    def _estimate_source_frames(self, output_frames: int) -> int:
        if self._opened_output_sample_rate <= 0 or self._content_sample_rate <= 0:
            return output_frames
        ratio = self._content_sample_rate / self._opened_output_sample_rate
        estimated = int(np.ceil(output_frames * ratio)) + 8
        return max(1, estimated)