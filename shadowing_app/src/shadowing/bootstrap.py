from __future__ import annotations

from pathlib import Path
from typing import Any

from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.audio_behavior_classifier import AudioBehaviorClassifier
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.live_audio_matcher import LiveAudioMatcher
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.fusion.evidence_fuser import EvidenceFuser
from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import RealtimeRuntimeConfig, ShadowingRuntime
from shadowing.telemetry.event_logger import EventLogger


def build_runtime(config: dict[str, Any]) -> ShadowingRuntime:
    lesson_base_dir = str(config.get("lesson_base_dir", "assets/lessons"))
    playback_cfg = dict(config.get("playback", {}))
    capture_cfg = dict(config.get("capture", {}))
    asr_cfg = dict(config.get("asr", {}))
    alignment_cfg = dict(config.get("alignment", {}))
    control_cfg = dict(config.get("control", {}))
    runtime_cfg = dict(config.get("runtime", {}))
    signal_cfg = dict(config.get("signal", {}))
    adaptation_cfg = dict(config.get("adaptation", {}))
    session_cfg = dict(config.get("session", {}))
    device_context = dict(config.get("device_context", {}))
    debug_cfg = dict(config.get("debug", {}))
    audio_match_cfg = dict(config.get("audio_match", {}))

    session_dir = str(session_cfg.get("session_dir", "runtime/latest_session"))
    event_logging = bool(session_cfg.get("event_logging", False))
    debug_enabled = bool(debug_cfg.get("enabled", False))
    repo = FileLessonRepository(lesson_base_dir)

    player = SoundDevicePlayer(
        PlaybackConfig(
            sample_rate=int(playback_cfg.get("sample_rate", 44100)),
            channels=int(playback_cfg.get("channels", 1)),
            device=playback_cfg.get("device"),
            latency=playback_cfg.get("latency", "low"),
            blocksize=int(playback_cfg.get("blocksize", 0)),
            bluetooth_output_offset_sec=float(playback_cfg.get("bluetooth_output_offset_sec", 0.0)),
        )
    )

    capture_backend = str(capture_cfg.get("backend", "sounddevice")).strip().lower()
    if capture_backend == "soundcard":
        from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
        recorder = SoundCardRecorder(
            sample_rate_in=int(capture_cfg.get("device_sample_rate", 48000)),
            target_sample_rate=int(capture_cfg.get("target_sample_rate", 16000)),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            block_frames=int(capture_cfg.get("blocksize", 1440) or 1440),
        )
    elif capture_backend == "sounddevice":
        from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
        recorder = SoundDeviceRecorder(
            sample_rate_in=int(capture_cfg.get("device_sample_rate", 48000)),
            target_sample_rate=int(capture_cfg.get("target_sample_rate", 16000)),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            dtype=str(capture_cfg.get("dtype", "float32")),
            blocksize=int(capture_cfg.get("blocksize", 0)),
            latency=capture_cfg.get("latency", "low"),
        )
    else:
        raise ValueError(f"Unsupported capture backend: {capture_backend!r}")

    asr_mode = str(asr_cfg.get("mode", "sherpa")).strip().lower()
    if asr_mode == "fake":
        asr = FakeASRProvider(FakeAsrConfig())
    elif asr_mode == "sherpa":
        asr = SherpaStreamingProvider(
            model_config=asr_cfg,
            hotwords=str(asr_cfg.get("hotwords", "")),
            sample_rate=int(asr_cfg.get("sample_rate", 16000)),
            emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.08)),
            enable_endpoint=bool(asr_cfg.get("enable_endpoint", True)),
            debug_feed=bool(asr_cfg.get("debug_feed", False)),
            debug_feed_every_n_chunks=int(asr_cfg.get("debug_feed_every_n_chunks", 20)),
        )
    else:
        raise ValueError(f"Unsupported ASR mode: {asr_mode!r}")

    aligner = IncrementalAligner(
        window_back=int(alignment_cfg.get("window_back", 8)),
        window_ahead=int(alignment_cfg.get("window_ahead", 40)),
        stable_frames=int(alignment_cfg.get("stable_frames", 2)),
        min_confidence=float(alignment_cfg.get("min_confidence", 0.60)),
        backward_lock_frames=int(alignment_cfg.get("backward_lock_frames", 3)),
        clause_boundary_bonus=float(alignment_cfg.get("clause_boundary_bonus", 0.15)),
        cross_clause_backward_extra_penalty=float(alignment_cfg.get("cross_clause_backward_extra_penalty", 0.20)),
        debug=bool(alignment_cfg.get("debug", False)),
        max_hyp_tokens=int(alignment_cfg.get("max_hyp_tokens", 16)),
        weak_commit_min_conf=float(alignment_cfg.get("weak_commit_min_conf", 0.82)),
        weak_commit_min_local_match=float(alignment_cfg.get("weak_commit_min_local_match", 0.80)),
        weak_commit_min_advance=int(alignment_cfg.get("weak_commit_min_advance", 3)),
    )
    policy = ControlPolicy(**control_cfg)
    controller = StateMachineController(
        policy=policy,
        disable_seek=bool(control_cfg.get("disable_seek", False)),
        debug=debug_enabled,
    )
    signal_monitor = SignalQualityMonitor(
        min_vad_rms=float(signal_cfg.get("min_vad_rms", 0.006)),
        vad_noise_multiplier=float(signal_cfg.get("vad_noise_multiplier", 2.8)),
    )
    latency_calibrator = LatencyCalibrator()
    auto_tuner = RuntimeAutoTuner()

    profile_path = str(adaptation_cfg.get("profile_path", "runtime/device_profiles.json"))
    profile_store = ProfileStore(profile_path)
    event_logger = EventLogger(session_dir=session_dir, enabled=event_logging)

    reference_audio_store = ReferenceAudioStore(lesson_base_dir)
    live_audio_matcher = LiveAudioMatcher(
        search_window_sec=float(audio_match_cfg.get("search_window_sec", 3.0)),
        match_window_sec=float(audio_match_cfg.get("match_window_sec", 1.8)),
        update_interval_sec=float(audio_match_cfg.get("update_interval_sec", 0.12)),
        min_frames_for_match=int(audio_match_cfg.get("min_frames_for_match", 20)),
        ring_buffer_sec=float(audio_match_cfg.get("ring_buffer_sec", 6.0)),
    )
    audio_behavior_classifier = AudioBehaviorClassifier()
    evidence_fuser = EvidenceFuser(
        text_priority_threshold=float(audio_match_cfg.get("text_priority_threshold", 0.72)),
        audio_takeover_threshold=float(audio_match_cfg.get("audio_takeover_threshold", 0.62)),
    )

    enriched_device_context = dict(device_context)
    enriched_device_context["capture_backend"] = capture_backend
    enriched_device_context["session_dir"] = str(Path(session_dir).expanduser().resolve())

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        device_context=enriched_device_context,
        signal_monitor=signal_monitor,
        latency_calibrator=latency_calibrator,
        auto_tuner=auto_tuner,
        profile_store=profile_store,
        event_logger=event_logger,
        reference_audio_store=reference_audio_store,
        live_audio_matcher=live_audio_matcher,
        audio_behavior_classifier=audio_behavior_classifier,
        evidence_fuser=evidence_fuser,
        audio_queue_maxsize=int(runtime_cfg.get("audio_queue_maxsize", 150)),
        loop_interval_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
        debug=debug_enabled,
    )
    runtime = ShadowingRuntime(
        orchestrator=orchestrator,
        config=RealtimeRuntimeConfig(
            tick_sleep_sec=float(runtime_cfg.get("loop_interval_sec", 0.03))
        ),
    )
    return runtime
