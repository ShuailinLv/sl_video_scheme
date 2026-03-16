from __future__ import annotations
import threading
import time
from collections.abc import Callable
import numpy as np
import pythoncom
import soundcard as sc
from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler


class SoundCardRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        block_frames: int = 1440,
        include_loopback: bool = False,
        debug_level_meter: bool = False,
        debug_level_every_n_blocks: int = 20,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.block_frames = max(128, int(block_frames))
        self.include_loopback = bool(include_loopback)
        self.debug_level_meter = bool(debug_level_meter)
        self.debug_level_every_n_blocks = max(1, int(debug_level_every_n_blocks))
        self._callback: Callable[[bytes], None] | None = None
        self._mic = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._opened_channels: int | None = None
        self._opened_samplerate: int | None = None
        self._debug_counter = 0
        self._resampler: AudioResampler | None = None
        self._last_error: Exception | None = None

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._running:
            return
        self._callback = on_audio_frame
        self._mic = self._resolve_microphone(self.device, self.include_loopback)
        open_candidates = self._build_open_candidates()
        last_error: Exception | None = None
        for sr, ch in open_candidates:
            try:
                with self._mic.recorder(samplerate=sr, channels=ch) as rec:
                    _ = rec.record(numframes=min(self.block_frames, 256))
                self._opened_samplerate = int(sr)
                self._opened_channels = int(ch)
                self._resampler = AudioResampler(src_rate=self._opened_samplerate, dst_rate=self.target_sample_rate)
                last_error = None
                break
            except Exception as e:
                last_error = e
        if last_error is not None or self._opened_samplerate is None or self._opened_channels is None:
            msg = str(last_error)
            if "0x80070005" in msg:
                raise RuntimeError(
                    "Failed to open microphone with soundcard: access denied (0x80070005). Please enable Windows microphone privacy permissions and close apps using the mic."
                )
            raise RuntimeError(f"Failed to open microphone with soundcard. device={self.device!r}, last_error={last_error}")
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def close(self) -> None:
        self.stop()

    def _capture_loop(self) -> None:
        assert self._mic is not None
        assert self._callback is not None
        assert self._opened_samplerate is not None
        assert self._opened_channels is not None
        pythoncom.CoInitialize()
        try:
            with self._mic.recorder(samplerate=self._opened_samplerate, channels=self._opened_channels) as rec:
                while self._running:
                    data = rec.record(numframes=self.block_frames)
                    if data is None:
                        time.sleep(0.005)
                        continue
                    audio = np.asarray(data, dtype=np.float32)
                    if audio.ndim == 1:
                        audio = audio[:, None]
                    if audio.shape[1] > 1:
                        audio = np.mean(audio, axis=1, keepdims=True)
                    mono = np.squeeze(audio, axis=1).astype(np.float32, copy=False)
                    self._debug_counter += 1
                    if self.debug_level_meter and (self._debug_counter <= 3 or self._debug_counter % self.debug_level_every_n_blocks == 0):
                        _rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                        _peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                    if self._resampler is None:
                        raise RuntimeError("SoundCardRecorder resampler is not initialized.")
                    pcm16_bytes = self._resampler.process_float_mono(mono)
                    self._callback(pcm16_bytes)
        except Exception as e:
            self._last_error = e
        finally:
            pythoncom.CoUninitialize()
            self._running = False

    def _build_open_candidates(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []
        candidate_srs: list[int] = []
        for sr in [self.sample_rate_in, 48000, 44100, 16000]:
            if sr > 0 and sr not in candidate_srs:
                candidate_srs.append(sr)
        candidate_channels: list[int] = []
        for ch in [1, self.channels, 2]:
            if ch > 0 and ch not in candidate_channels:
                candidate_channels.append(ch)
        for sr in candidate_srs:
            for ch in candidate_channels:
                candidates.append((int(sr), int(ch)))
        return candidates

    def _resolve_microphone(self, device: int | str | None, include_loopback: bool):
        mics = list(sc.all_microphones(include_loopback=include_loopback))
        if not mics:
            raise RuntimeError("No microphones found via soundcard.")
        if device is None:
            default_mic = sc.default_microphone()
            if default_mic is None:
                raise RuntimeError("No default microphone found via soundcard.")
            return default_mic
        if isinstance(device, int):
            if 0 <= device < len(mics):
                return mics[device]
            raise ValueError(
                f"Soundcard microphone index out of range: {device}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        key = str(device).strip().lower()
        if key.isdigit():
            idx = int(key)
            if 0 <= idx < len(mics):
                return mics[idx]
            raise ValueError(
                f"Soundcard microphone index out of range: {idx}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        for mic in mics:
            if key in mic.name.lower():
                return mic
        raise ValueError(
            f"No matching microphone found for {device!r}. For soundcard backend, pass either a soundcard microphone list index or a device name substring."
        )
