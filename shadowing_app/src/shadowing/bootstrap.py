from __future__ import annotations

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig, FakeAsrStep
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import ShadowingRuntime
from shadowing.types import AsrEventType


def _build_fake_asr_config(asr_cfg: dict) -> FakeAsrConfig:
    scripted_steps_raw = asr_cfg.get("scripted_steps", [])
    scripted_steps: list[FakeAsrStep] = []

    for item in scripted_steps_raw:
        if isinstance(item, FakeAsrStep):
            scripted_steps.append(item)
            continue

        if not isinstance(item, dict):
            raise ValueError(f"Invalid fake ASR scripted step: {item!r}")

        event_type_raw = str(item.get("event_type", "partial")).lower()
        if event_type_raw == "final":
            event_type = AsrEventType.FINAL
        else:
            event_type = AsrEventType.PARTIAL

        scripted_steps.append(
            FakeAsrStep(
                offset_sec=float(item.get("offset_sec", 0.0)),
                text=str(item.get("text", "")),
                event_type=event_type,
            )
        )

    return FakeAsrConfig(
        scripted_steps=scripted_steps,
        reference_text=str(asr_cfg.get("reference_text", "")),
        chars_per_sec=float(asr_cfg.get("chars_per_sec", 4.0)),
        emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.10)),
        emit_final_on_endpoint=bool(asr_cfg.get("emit_final_on_endpoint", True)),
        sample_rate=int(asr_cfg.get("sample_rate", 16000)),
        bytes_per_sample=int(asr_cfg.get("bytes_per_sample", 2)),
        channels=int(asr_cfg.get("channels", 1)),
        vad_rms_threshold=float(asr_cfg.get("vad_rms_threshold", 0.01)),
        vad_min_active_ms=float(asr_cfg.get("vad_min_active_ms", 30.0)),
    )


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    playback_cfg = config["playback"]
    player = SoundDevicePlayer(
        PlaybackConfig(
            sample_rate=int(playback_cfg["sample_rate"]),
            channels=int(playback_cfg.get("channels", 1)),
            device=playback_cfg.get("device"),
            latency=playback_cfg.get("latency", "low"),
            blocksize=int(playback_cfg.get("blocksize", 0)),
            bluetooth_output_offset_sec=float(playback_cfg.get("bluetooth_output_offset_sec", 0.0)),
        )
    )

    capture_cfg = config["capture"]
    capture_backend = str(capture_cfg.get("backend", "sounddevice")).strip().lower()

    if capture_backend == "soundcard":
        recorder = SoundCardRecorder(
            sample_rate_in=int(capture_cfg["device_sample_rate"]),
            target_sample_rate=int(capture_cfg["target_sample_rate"]),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            block_frames=int(capture_cfg.get("block_frames", capture_cfg.get("blocksize", 1440))),
            include_loopback=bool(capture_cfg.get("include_loopback", False)),
            debug_level_meter=bool(capture_cfg.get("debug_level_meter", False)),
            debug_level_every_n_blocks=int(capture_cfg.get("debug_level_every_n_blocks", 20)),
        )
    else:
        recorder = SoundDeviceRecorder(
            sample_rate_in=int(capture_cfg["device_sample_rate"]),
            target_sample_rate=int(capture_cfg["target_sample_rate"]),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            dtype=capture_cfg.get("dtype", "float32"),
            blocksize=int(capture_cfg.get("blocksize", 0)),
            latency=capture_cfg.get("latency", "low"),
        )

    asr_cfg = config["asr"]
    asr_mode = str(asr_cfg.get("mode", "sherpa")).lower()

    if asr_mode == "fake":
        asr = FakeASRProvider(_build_fake_asr_config(asr_cfg))
    else:
        asr = SherpaStreamingProvider(
            model_config=asr_cfg,
            hotwords=str(asr_cfg.get("hotwords", "")),
            sample_rate=int(asr_cfg.get("sample_rate", 16000)),
            emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.08)),
            enable_endpoint=bool(asr_cfg.get("enable_endpoint", True)),
            debug_feed=bool(asr_cfg.get("debug_feed", False)),
            debug_feed_every_n_chunks=int(asr_cfg.get("debug_feed_every_n_chunks", 20)),
        )

    align_cfg = config.get("alignment", {})
    aligner = IncrementalAligner(
        window_back=int(align_cfg.get("window_back", 8)),
        window_ahead=int(align_cfg.get("window_ahead", 40)),
        stable_frames=int(align_cfg.get("stable_frames", 2)),
        min_confidence=float(align_cfg.get("min_confidence", 0.60)),
        backward_lock_frames=int(align_cfg.get("backward_lock_frames", 3)),
        clause_boundary_bonus=float(align_cfg.get("clause_boundary_bonus", 0.15)),
        cross_clause_backward_extra_penalty=float(
            align_cfg.get("cross_clause_backward_extra_penalty", 0.20)
        ),
        debug=bool(align_cfg.get("debug", False)),
        max_hyp_tokens=int(align_cfg.get("max_hyp_tokens", 16)),
    )

    control_cfg = config.get("control", {})
    policy = ControlPolicy(
        target_lead_sec=float(control_cfg.get("target_lead_sec", 0.15)),
        hold_if_lead_sec=float(control_cfg.get("hold_if_lead_sec", 0.90)),
        resume_if_lead_sec=float(control_cfg.get("resume_if_lead_sec", 0.28)),
        seek_if_lag_sec=float(control_cfg.get("seek_if_lag_sec", -1.80)),
        min_confidence=float(control_cfg.get("min_confidence", 0.75)),
        seek_cooldown_sec=float(control_cfg.get("seek_cooldown_sec", 1.20)),
        gain_following=float(control_cfg.get("gain_following", 0.55)),
        gain_transition=float(control_cfg.get("gain_transition", 0.80)),
        gain_soft_duck=float(control_cfg.get("gain_soft_duck", 0.42)),
        recover_after_seek_sec=float(control_cfg.get("recover_after_seek_sec", 0.60)),
        startup_grace_sec=float(control_cfg.get("startup_grace_sec", 0.80)),
        low_confidence_hold_sec=float(control_cfg.get("low_confidence_hold_sec", 0.60)),
        bootstrapping_sec=float(control_cfg.get("bootstrapping_sec", 1.80)),
        guide_play_sec=float(control_cfg.get("guide_play_sec", 2.20)),
        no_progress_hold_min_play_sec=float(control_cfg.get("no_progress_hold_min_play_sec", 4.00)),
        speaking_recent_sec=float(control_cfg.get("speaking_recent_sec", 0.90)),
        progress_stale_sec=float(control_cfg.get("progress_stale_sec", 1.10)),
        hold_trend_sec=float(control_cfg.get("hold_trend_sec", 0.75)),
        hold_extra_lead_sec=float(control_cfg.get("hold_extra_lead_sec", 0.18)),
        low_confidence_continue_sec=float(control_cfg.get("low_confidence_continue_sec", 1.40)),
        tracking_quality_hold_min=float(control_cfg.get("tracking_quality_hold_min", 0.60)),
        tracking_quality_seek_min=float(control_cfg.get("tracking_quality_seek_min", 0.72)),
        resume_from_hold_event_fresh_sec=float(control_cfg.get("resume_from_hold_event_fresh_sec", 0.45)),
        resume_from_hold_speaking_lead_slack_sec=float(
            control_cfg.get("resume_from_hold_speaking_lead_slack_sec", 0.45)
        ),
        reacquire_soft_duck_sec=float(control_cfg.get("reacquire_soft_duck_sec", 2.00)),
    )

    controller = StateMachineController(
        policy=policy,
        disable_seek=bool(control_cfg.get("disable_seek", False)),
    )

    runtime_cfg = config.get("runtime", {})
    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        audio_queue_maxsize=int(runtime_cfg.get("audio_queue_maxsize", 150)),
        asr_event_queue_maxsize=int(runtime_cfg.get("asr_event_queue_maxsize", 64)),
        loop_interval_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
    )

    if "runtime" in config:
        orchestrator.configure_runtime(config["runtime"])
    if "debug" in config:
        orchestrator.configure_debug(config["debug"])

    return ShadowingRuntime(orchestrator)