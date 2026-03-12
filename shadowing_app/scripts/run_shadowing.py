from __future__ import annotations

from shadowing.bootstrap import build_runtime


def main() -> None:
    config = {
        "lesson_base_dir": "assets/lessons",
        "playback": {
            "sample_rate": 48000,
            "device": None,
            "bluetooth_output_offset_sec": 0.18,
        },
        "capture": {
            "device_sample_rate": 48000,
            "target_sample_rate": 16000,
            "device": None,
        },
        "asr": {
            "hotwords": "",
        },
    }

    runtime = build_runtime(config)
    runtime.run("demo_lesson")


if __name__ == "__main__":
    main()