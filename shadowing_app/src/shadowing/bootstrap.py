from __future__ import annotations

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.playback.sounddevice_player import SoundDevicePlayer
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.control.adaptive_controller import AdaptiveController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.runtime import ShadowingRuntime


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    player = SoundDevicePlayer(
        sample_rate=config["playback"]["sample_rate"],
        channels=1,
        device=config["playback"].get("device"),
        bluetooth_output_offset_sec=config["playback"].get(
            "bluetooth_output_offset_sec", 0.0
        ),
    )

    capture_cfg = config["capture"]
    recorder = SoundDeviceRecorder(
        sample_rate_in=capture_cfg["device_sample_rate"],
        target_sample_rate=capture_cfg["target_sample_rate"],
        channels=1,
        device=capture_cfg.get("device"),
        dtype=capture_cfg.get("dtype", "float32"),
        blocksize=int(capture_cfg.get("blocksize", 0)),
        latency=capture_cfg.get("latency", "low"),
    )

    asr = SherpaStreamingProvider(
        model_config=config["asr"],
        hotwords=config["asr"].get("hotwords", ""),
    )

    aligner = IncrementalAligner()

    control_cfg = config.get("control", {})
    controller = AdaptiveController(
        ducking_only=bool(control_cfg.get("ducking_only", False)),
        disable_seek=bool(control_cfg.get("disable_seek", False)),
        disable_hold=bool(control_cfg.get("disable_hold", False)),
    )

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
    )

    if "runtime" in config and hasattr(orchestrator, "configure_runtime"):
        orchestrator.configure_runtime(config["runtime"])

    return ShadowingRuntime(orchestrator)