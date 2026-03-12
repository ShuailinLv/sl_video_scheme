from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import pythoncom
import soundcard as sc

from shadowing.interfaces.recorder import Recorder


class SoundCardRecorder(Recorder):
    """
    Windows 优先录音实现，基于 soundcard(WASAPI)。

    特点：
    - 兼容现有 Recorder 接口
    - 支持指定设备 index 或设备名子串
    - 后台线程持续拉取音频
    - 自动下混到 mono
    - 自动重采样到 target_sample_rate
    - 输出 little-endian int16 PCM bytes，兼容现有 ASRProvider.feed_pcm16()
    - 带轻量级电平调试打印，便于判断麦克风是否真正录到声音
    """

    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        block_frames: int = 1024,
        include_loopback: bool = False,
        debug_level_meter: bool = True,
        debug_level_every_n_blocks: int = 20,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.block_frames = int(block_frames)
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

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._running:
            return

        self._callback = on_audio_frame
        self._mic = self._resolve_microphone(self.device, self.include_loopback)

        open_candidates = self._build_open_candidates()

        last_error: Exception | None = None
        for sr, ch in open_candidates:
            try:
                print(
                    f"[REC-SC] trying mic={self._mic.name!r} "
                    f"samplerate={sr} channels={ch}"
                )

                # 这里只做轻量试开，确保该组合可用
                with self._mic.recorder(samplerate=sr, channels=ch) as rec:
                    _ = rec.record(numframes=min(self.block_frames, 256))

                self._opened_samplerate = sr
                self._opened_channels = ch
                print(
                    f"[REC-SC] opened mic={self._mic.name!r} "
                    f"samplerate={sr} channels={ch}"
                )
                last_error = None
                break
            except Exception as e:
                last_error = e

        if last_error is not None or self._opened_samplerate is None or self._opened_channels is None:
            msg = str(last_error)
            if "0x80070005" in msg:
                raise RuntimeError(
                    "Failed to open microphone with soundcard: access denied (0x80070005). "
                    "Please enable Windows microphone privacy permissions and close apps using the mic."
                )
            raise RuntimeError(
                "Failed to open microphone with soundcard. "
                f"device={self.device!r}, last_error={last_error}"
            )

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

        # 关键修复：后台线程初始化 COM，避免 WASAPI 在线程里报 0x800401f0
        pythoncom.CoInitialize()
        try:
            with self._mic.recorder(
                samplerate=self._opened_samplerate,
                channels=self._opened_channels,
            ) as rec:
                while self._running:
                    data = rec.record(numframes=self.block_frames)

                    if data is None:
                        time.sleep(0.005)
                        continue

                    audio = np.asarray(data, dtype=np.float32)

                    # shape 统一为 [frames, channels]
                    if audio.ndim == 1:
                        audio = audio[:, None]

                    # 多声道下混为 mono
                    if audio.shape[1] > 1:
                        audio = np.mean(audio, axis=1, keepdims=True)

                    mono = np.squeeze(audio, axis=1).astype(np.float32, copy=False)

                    if self.debug_level_meter:
                        self._debug_counter += 1
                        if self._debug_counter % self.debug_level_every_n_blocks == 0:
                            rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                            print(f"[REC-SC] rms={rms:.5f} peak={peak:.5f}")

                    src_sr = self._opened_samplerate
                    if src_sr != self.target_sample_rate:
                        mono = self._resample_linear(mono, src_sr, self.target_sample_rate)

                    pcm16 = np.clip(mono, -1.0, 1.0)
                    pcm16 = (pcm16 * 32767.0).astype(np.int16)

                    self._callback(pcm16.tobytes())
        except Exception as e:
            print(f"[REC-SC] capture loop stopped due to error: {e}")
        finally:
            pythoncom.CoUninitialize()
            self._running = False

    def _build_open_candidates(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []

        candidate_srs: list[int] = []
        for sr in [self.sample_rate_in, 48000, 44100]:
            if sr > 0 and sr not in candidate_srs:
                candidate_srs.append(sr)

        candidate_channels: list[int] = []
        for ch in [1, 2, self.channels]:
            if ch > 0 and ch not in candidate_channels:
                candidate_channels.append(ch)

        for sr in candidate_srs:
            for ch in candidate_channels:
                candidates.append((sr, ch))

        return candidates

    def _resolve_microphone(self, device: int | str | None, include_loopback: bool):
        mics = list(sc.all_microphones(include_loopback=include_loopback))
        if not mics:
            raise RuntimeError("No microphones found via soundcard.")

        print("[REC-SC] available microphones:")
        for idx, mic in enumerate(mics):
            print(f"  [{idx}] {mic.name!r}")

        if device is None:
            default_mic = sc.default_microphone()
            if default_mic is None:
                raise RuntimeError("No default microphone found via soundcard.")
            print(f"[REC-SC] using default microphone: {default_mic.name!r}")
            return default_mic

        if isinstance(device, int):
            if 0 <= device < len(mics):
                print(f"[REC-SC] using microphone index={device}: {mics[device].name!r}")
                return mics[device]
            raise ValueError(f"Microphone index out of range for soundcard: {device}")

        key = str(device).strip().lower()
        for mic in mics:
            if key in mic.name.lower():
                print(f"[REC-SC] matched microphone {device!r} -> {mic.name!r}")
                return mic

        raise ValueError(f"No matching microphone found for {device!r}")

    @staticmethod
    def _resample_linear(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr or x.size == 0:
            return x.astype(np.float32, copy=False)

        duration = x.shape[0] / float(src_sr)
        dst_n = max(1, int(round(duration * dst_sr)))

        src_idx = np.linspace(0, x.shape[0] - 1, num=x.shape[0], dtype=np.float32)
        dst_idx = np.linspace(0, x.shape[0] - 1, num=dst_n, dtype=np.float32)

        y = np.interp(dst_idx, src_idx, x).astype(np.float32)
        return y