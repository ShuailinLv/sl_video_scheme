import queue
import threading
import time
import _bootstrap  # noqa: F401

from shadowing.realtime.capture.device_utils import (
    print_input_devices,
    get_default_input_device_index,
    pick_working_input_config,
)
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.capture.device_utils import pick_working_input_config
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder


def main() -> None:
    q: queue.Queue[bytes] = queue.Queue(maxsize=8)
    running = True

    rec_cfg = pick_working_input_config()
    if rec_cfg is None:
        raise RuntimeError("No working input device config found.")

    recorder = SoundDeviceRecorder(
        sample_rate_in=rec_cfg["samplerate"],
        target_sample_rate=16000,
        channels=rec_cfg["channels"],
        device=rec_cfg["device"],
        dtype=rec_cfg["dtype"],
    )

    asr = FakeASRProvider(
        FakeAsrConfig(
            reference_text="今天天气真好我们一起练习中文",
            chars_per_sec=4.5,
            emit_partial_interval_sec=0.10,
            sample_rate=16000,
        )
    )
    asr.start()

    def on_audio_frame(pcm: bytes) -> None:
        try:
            q.put_nowait(pcm)
        except queue.Full:
            try:
                _ = q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(pcm)
            except queue.Full:
                pass

    def worker() -> None:
        while running:
            try:
                pcm = q.get(timeout=0.05)
            except queue.Empty:
                continue

            asr.feed_pcm16(pcm)
            events = asr.poll_events()
            for e in events:
                print(f"[{e.event_type}] text={e.text} norm={e.normalized_text} py={e.pinyin_seq}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    recorder.start(on_audio_frame)
    print("Recording... speak something. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
        recorder.close()
        asr.close()


if __name__ == "__main__":
    main()