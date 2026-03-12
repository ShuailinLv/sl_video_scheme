from __future__ import annotations

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.playback.sounddevice_player import SoundDevicePlayer
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.runtime import ShadowingRuntime


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    player = SoundDevicePlayer(
        sample_rate=config["playback"]["sample_rate"],
        channels=1,
        device=config["playback"].get("device"),
        bluetooth_output_offset_sec=config["playback"].get("bluetooth_output_offset_sec", 0.0),
    )

    recorder = SoundDeviceRecorder(
        sample_rate_in=config["capture"]["device_sample_rate"],
        target_sample_rate=config["capture"]["target_sample_rate"],
        channels=1,
        device=config["capture"].get("device"),
    )

    asr = SherpaStreamingProvider(
        model_config=config["asr"],
        hotwords=config["asr"].get("hotwords", ""),
    )

    aligner = IncrementalAligner()
    controller = StateMachineController()

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
    )
    return ShadowingRuntime(orchestrator)