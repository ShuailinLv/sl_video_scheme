from __future__ import annotations

import queue
import threading
from collections.abc import Iterable

import numpy as np
import sounddevice as sd

from shadowing.audio.playback_config import PlaybackConfig


class SoundDevicePlayer:
    def __init__(self, config: PlaybackConfig) -> None:
        self.config = config
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.OutputStream | None = None
        self._started = False
        self._lock = threading.Lock()
        self._closed = False
        self._resolved_device: int | None = None

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Player already closed")
            if self._started:
                return

            self._resolved_device = self._resolve_output_device(self.config.device)

            self._stream = sd.OutputStream(
                samplerate=int(self.config.sample_rate),
                channels=int(self.config.channels),
                dtype="float32",
                callback=self._callback,
                blocksize=int(self.config.blocksize),
                latency=self.config.latency,
                device=self._resolved_device,
            )
            self._stream.start()
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                finally:
                    self._stream.close()
                    self._stream = None
            self._started = False

    def close(self) -> None:
        if self._closed:
            return
        self.stop()
        self._closed = True

    def enqueue(self, audio: np.ndarray) -> None:
        if audio is None:
            return
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        self._queue.put(arr)

    def enqueue_many(self, audios: Iterable[np.ndarray]) -> None:
        for audio in audios:
            self.enqueue(audio)

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _callback(self, outdata, frames, time_info, status) -> None:
        _ = time_info
        if status:
            pass

        out = np.zeros((frames, int(self.config.channels)), dtype=np.float32)
        filled = 0

        while filled < frames:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break

            if chunk.ndim != 1:
                chunk = chunk.reshape(-1)

            remain = frames - filled
            take = min(remain, chunk.shape[0])

            mono = chunk[:take].astype(np.float32, copy=False)
            if int(self.config.channels) == 1:
                out[filled : filled + take, 0] = mono
            else:
                out[filled : filled + take, :] = mono[:, None]

            filled += take

            leftover = chunk[take:]
            if leftover.size > 0:
                self._queue.queue.appendleft(leftover)
                break

        outdata[:] = out

    def _resolve_output_device(self, device: int | str | None) -> int | None:
        if device is None:
            default_in, default_out = sd.default.device
            _ = default_in
            if default_out is None or int(default_out) < 0:
                return None
            return int(default_out)

        if isinstance(device, int):
            info = sd.query_devices(device)
            max_out = int(info["max_output_channels"])
            if max_out <= 0:
                raise ValueError(f"Device index {device} is not an output device")
            return int(device)

        target = str(device).strip().lower()
        if not target:
            default_in, default_out = sd.default.device
            _ = default_in
            if default_out is None or int(default_out) < 0:
                return None
            return int(default_out)

        matched_index: int | None = None
        matched_name: str | None = None

        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if int(dev["max_output_channels"]) <= 0:
                continue
            name = str(dev["name"])
            if target in name.lower():
                matched_index = int(idx)
                matched_name = name
                break

        if matched_index is None:
            candidates: list[str] = []
            for idx, dev in enumerate(devices):
                if int(dev["max_output_channels"]) <= 0:
                    continue
                candidates.append(f"[{idx}] {dev['name']}")
            joined = "\n".join(candidates[:50])
            raise ValueError(
                "Output device name not found: "
                f"{device!r}\nAvailable output devices:\n{joined}"
            )

        _ = matched_name
        return matched_index