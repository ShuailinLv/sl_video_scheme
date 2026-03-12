from __future__ import annotations

from typing import Callable, Any

import numpy as np
import sounddevice as sd

from shadowing.interfaces.recorder import Recorder


class SoundDeviceRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        dtype: str = "float32",
        blocksize: int = 0,
        latency: str | float = "low",
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.dtype = dtype
        self.blocksize = blocksize
        self.latency = latency

        self._stream: sd.InputStream | None = None
        self._callback: Callable[[bytes], None] | None = None

        self._opened_channels: int | None = None
        self._opened_samplerate: int | None = None
        self._resolved_input_device: int | None = None

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._stream is not None:
            return

        self._callback = on_audio_frame

        input_device_index = self._resolve_input_device(self.device)
        self._resolved_input_device = input_device_index

        dev_info = sd.query_devices(input_device_index, "input")
        max_in = int(dev_info["max_input_channels"])
        default_sr = int(float(dev_info["default_samplerate"]))
        device_name = str(dev_info["name"])

        candidate_sample_rates: list[int] = []
        for sr in [self.sample_rate_in, default_sr]:
            if sr > 0 and sr not in candidate_sample_rates:
                candidate_sample_rates.append(sr)

        candidate_channels: list[int] = []
        for ch in [1, 2, max_in]:
            if ch > 0 and ch <= max_in and ch not in candidate_channels:
                candidate_channels.append(ch)

        last_error: Exception | None = None

        for sr in candidate_sample_rates:
            for ch in candidate_channels:
                try:
                    print(
                        f"[REC] trying raw_device={input_device_index} "
                        f"name={device_name!r} samplerate={sr} channels={ch} dtype={self.dtype}"
                    )

                    self._stream = sd.InputStream(
                        samplerate=sr,
                        blocksize=self.blocksize,
                        device=input_device_index,
                        channels=ch,
                        dtype=self.dtype,
                        latency=self.latency,
                        callback=self._audio_callback,
                    )
                    self._stream.start()

                    self._opened_channels = ch
                    self._opened_samplerate = sr

                    print(
                        f"[REC] opened raw_device={input_device_index} "
                        f"name={device_name!r} samplerate={sr} channels={ch}"
                    )
                    return
                except Exception as e:
                    last_error = e
                    self._stream = None

        raise RuntimeError(
            "Failed to open input device with all candidate channel/sample-rate combinations. "
            f"raw_device={input_device_index}, name={device_name!r}, "
            f"max_input_channels={max_in}, default_samplerate={default_sr}. "
            f"Last error: {last_error}"
        )

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None

    def close(self) -> None:
        self.stop()

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self._callback is None:
            return

        if status:
            print(f"[REC] callback status: {status}")

        audio = np.asarray(indata)

        if audio.ndim == 1:
            audio = audio[:, None]

        if audio.shape[1] > 1:
            audio = np.mean(audio, axis=1, keepdims=True)

        mono = np.squeeze(audio, axis=1).astype(np.float32)

        src_sr = self._opened_samplerate or self.sample_rate_in
        if src_sr != self.target_sample_rate:
            mono = self._resample_linear(mono, src_sr, self.target_sample_rate)

        pcm16 = np.clip(mono, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)

        self._callback(pcm16.tobytes())

    def _resolve_input_device(self, device: int | str | None) -> int:
        """
        支持三种指定方式：
        1. None -> 默认输入设备
        2. int  -> 先按原始 sounddevice 索引解释；如果不是输入设备，再按“输入设备序号”解释
        3. str  -> 按输入设备名称模糊匹配
        """
        all_devices = sd.query_devices()
        input_devices = [
            (idx, dev)
            for idx, dev in enumerate(all_devices)
            if int(dev["max_input_channels"]) > 0
        ]

        self._print_input_device_map(input_devices)

        if device is None:
            default_input, _default_output = sd.default.device
            if default_input is None or default_input < 0:
                raise RuntimeError("No default input device available.")
            dev = all_devices[default_input]
            if int(dev["max_input_channels"]) <= 0:
                raise RuntimeError(f"Default input device is not valid: {dev}")
            print(f"[REC] using default input raw_device={default_input} name={dev['name']!r}")
            return int(default_input)

        if isinstance(device, int):
            # 方案 A：先按原始 raw index 解释
            if 0 <= device < len(all_devices):
                dev = all_devices[device]
                if int(dev["max_input_channels"]) > 0:
                    print(f"[REC] using raw input device index={device} name={dev['name']!r}")
                    return int(device)

            # 方案 B：再按“输入设备序号”解释（即第 N 个输入设备）
            if 0 <= device < len(input_devices):
                raw_idx, dev = input_devices[device]
                print(
                    f"[REC] input device {device} is not a valid raw input index; "
                    f"fallback to input-list ordinal -> raw_device={raw_idx}, name={dev['name']!r}"
                )
                return int(raw_idx)

            raise ValueError(
                f"Input device {device} is neither a valid raw input device index "
                f"nor a valid ordinal in the filtered input-device list."
            )

        # string case
        target = str(device).strip().lower()
        candidates: list[tuple[int, Any]] = []
        for idx, dev in input_devices:
            name = str(dev["name"]).lower()
            if target == name or target in name:
                candidates.append((idx, dev))

        if not candidates:
            raise ValueError(f"No matching input device found for: {device!r}")

        raw_idx, dev = candidates[0]
        print(f"[REC] matched input device name {device!r} -> raw_device={raw_idx}, name={dev['name']!r}")
        return int(raw_idx)

    @staticmethod
    def _print_input_device_map(input_devices: list[tuple[int, Any]]) -> None:
        print("[REC] available input devices (ordinal -> raw index):")
        for ordinal, (raw_idx, dev) in enumerate(input_devices):
            print(
                f"  [{ordinal}] raw={raw_idx} "
                f"name={dev['name']!r} "
                f"max_in={int(dev['max_input_channels'])} "
                f"default_sr={int(float(dev['default_samplerate']))}"
            )

    @staticmethod
    def _resample_linear(
        x: np.ndarray,
        src_sr: int,
        dst_sr: int,
    ) -> np.ndarray:
        if src_sr == dst_sr or x.size == 0:
            return x.astype(np.float32, copy=False)

        duration = x.shape[0] / float(src_sr)
        dst_n = max(1, int(round(duration * dst_sr)))

        src_idx = np.linspace(0, x.shape[0] - 1, num=x.shape[0], dtype=np.float32)
        dst_idx = np.linspace(0, x.shape[0] - 1, num=dst_n, dtype=np.float32)

        y = np.interp(dst_idx, src_idx, x).astype(np.float32)
        return y