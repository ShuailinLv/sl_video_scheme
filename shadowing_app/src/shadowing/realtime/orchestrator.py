from __future__ import annotations

import json
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.device_profile import DeviceProfile, build_device_profile
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.commercial_progress_estimator import CommercialProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import (
    AsrEventType,
    DeviceProfileSnapshot,
    LatencyCalibrationSnapshot,
    PlayerCommand,
    PlayerCommandType,
    PlaybackState,
    ReferenceMap,
)


@dataclass(slots=True)
class OrchestratorStats:
    audio_enqueued: int = 0
    audio_dropped: int = 0
    audio_q_high_watermark: int = 0
    raw_asr_events: int = 0
    normalized_asr_events: int = 0
    ticks: int = 0
    asr_frames_fed: int = 0
    asr_frames_skipped: int = 0
    asr_gate_open_count: int = 0
    asr_gate_close_count: int = 0
    asr_resets_from_silence: int = 0


class ShadowingOrchestrator:
    def __init__(
        self,
        *,
        repo,
        player,
        recorder,
        asr,
        aligner,
        controller,
        device_context: dict[str, Any] | None = None,
        signal_monitor: SignalQualityMonitor | None = None,
        latency_calibrator: LatencyCalibrator | None = None,
        auto_tuner: RuntimeAutoTuner | None = None,
        profile_store: ProfileStore | None = None,
        event_logger: EventLogger | None = None,
        audio_queue_maxsize: int = 150,
        asr_event_queue_maxsize: int = 64,
        loop_interval_sec: float = 0.03,
        debug: bool = False,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.device_context = dict(device_context or {})
        self.signal_monitor = signal_monitor or SignalQualityMonitor()
        self.latency_calibrator = latency_calibrator or LatencyCalibrator()
        self.auto_tuner = auto_tuner or RuntimeAutoTuner()
        self.profile_store = profile_store
        self.event_logger = event_logger

        self.audio_queue: queue.Queue[tuple[float, bytes]] = queue.Queue(maxsize=max(16, int(audio_queue_maxsize)))
        self.loop_interval_sec = float(loop_interval_sec)
        self.debug = bool(debug)

        self.normalizer = TextNormalizer()
        self.tracking_engine = TrackingEngine(self.aligner, debug=debug)
        self.progress_estimator = CommercialProgressEstimator()
        self.metrics = MetricsAggregator()

        self.stats = OrchestratorStats()

        self._lesson_id: str | None = None
        self._ref_map: ReferenceMap | None = None
        self._running = False
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent: float | None = None
        self._last_control_action_key: tuple[str, str] | None = None
        self._device_profile: DeviceProfile | None = None
        self._warm_start: dict[str, Any] = {}
        self._session_started_at_sec = 0.0

        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = 0.0
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0

        self._speech_open_rms = 0.010
        self._speech_keep_rms = 0.0065
        self._speech_open_peak = 0.030
        self._speech_keep_peak = 0.018
        self._speech_open_likelihood = 0.58
        self._speech_keep_likelihood = 0.42
        self._speech_tail_hold_sec = 0.38
        self._asr_reset_after_silence_sec = 1.15
        self._asr_reset_cooldown_sec = 0.90

    def configure_runtime(self, runtime_cfg: dict[str, Any]) -> None:
        if "loop_interval_sec" in runtime_cfg:
            self.loop_interval_sec = float(runtime_cfg["loop_interval_sec"])

    def configure_debug(self, debug_cfg: dict[str, Any]) -> None:
        self.debug = bool(debug_cfg.get("enabled", self.debug))

    def start_session(self, lesson_id: str) -> None:
        self._lesson_id = lesson_id
        self._ref_map = self.repo.load_reference_map(lesson_id)

        self.tracking_engine.reset(self._ref_map)
        self.progress_estimator.reset(self._ref_map, start_idx=0)
        self.controller.reset()

        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        chunks = self.repo.load_audio_chunks(lesson_id)
        self.player.load_chunks(chunks)

        self._session_started_at_sec = time.monotonic()
        self.metrics.mark_session_started(self._session_started_at_sec)
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent = None
        self._last_control_action_key = None

        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = self._session_started_at_sec
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0

        output_sr = chunks[0].sample_rate if chunks else 44100
        self._device_profile = self._build_initial_device_profile(output_sr)
        self.latency_calibrator.reset(self._device_profile)
        self.auto_tuner.reset(self._device_profile.reliability_tier)

        if self.profile_store is not None and self._device_profile is not None:
            self._warm_start = self.profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
            )
            self.auto_tuner.apply_warm_start(
                controller_policy=self.controller.policy,
                player=self.player,
                signal_monitor=self.signal_monitor,
                warm_start=self._warm_start,
            )

        self.asr.start()
        self.recorder.start(self._on_audio_frame)
        self.player.start()

        self._running = True

    def stop_session(self) -> None:
        if not self._running:
            return

        self._running = False

        try:
            self.recorder.stop()
        except Exception:
            pass

        try:
            self.asr.close()
        except Exception:
            pass

        try:
            self.player.stop()
        except Exception:
            pass

        self._persist_session_profile()
        self._persist_summary()

        try:
            self.player.close()
        except Exception:
            pass

        try:
            self.recorder.close()
        except Exception:
            pass

    def tick(self) -> None:
        if not self._running:
            return

        self.stats.ticks += 1

        self._drain_audio_queue()

        now_sec = time.monotonic()
        signal_snapshot = self.signal_monitor.snapshot(now_sec)

        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.48:
            self.metrics.observe_signal_active(now_sec)

        playback_status = self.player.get_status()
        if playback_status.generation != self._last_generation:
            self._last_generation = playback_status.generation
            self.tracking_engine.on_playback_generation_changed(playback_status.generation)
            self.progress_estimator.on_playback_generation_changed(now_sec)

        raw_events = self.asr.poll_raw_events()
        self.stats.raw_asr_events += len(raw_events)

        progress = None
        for raw_event in raw_events:
            if raw_event.event_type == AsrEventType.PARTIAL:
                self.metrics.observe_asr_partial(raw_event.emitted_at_sec)

            event = self.normalizer.normalize_raw_event(raw_event)
            if event is None:
                continue

            self.stats.normalized_asr_events += 1
            tracking = self.tracking_engine.update(event)
            if tracking is None:
                continue

            if self._last_tracking_mode != tracking.tracking_mode:
                self.metrics.observe_tracking_mode(tracking.tracking_mode.value)
                self._last_tracking_mode = tracking.tracking_mode

            if self.event_logger is not None:
                self.event_logger.log(
                    "tracking_snapshot",
                    {
                        "candidate_ref_idx": tracking.candidate_ref_idx,
                        "committed_ref_idx": tracking.committed_ref_idx,
                        "candidate_ref_time_sec": tracking.candidate_ref_time_sec,
                        "tracking_mode": tracking.tracking_mode.value,
                        "overall_score": tracking.tracking_quality.overall_score,
                        "observation_score": tracking.tracking_quality.observation_score,
                        "temporal_consistency_score": tracking.tracking_quality.temporal_consistency_score,
                        "anchor_score": tracking.tracking_quality.anchor_score,
                        "is_reliable": tracking.tracking_quality.is_reliable,
                        "confidence": tracking.confidence,
                        "stable": tracking.stable,
                        "local_match_ratio": tracking.local_match_ratio,
                        "repeat_penalty": tracking.repeat_penalty,
                        "monotonic_consistency": tracking.monotonic_consistency,
                        "anchor_consistency": tracking.anchor_consistency,
                        "matched_text": tracking.matched_text,
                        "emitted_at_sec": tracking.emitted_at_sec,
                    },
                )

            progress = self.progress_estimator.update(
                tracking=tracking,
                signal_quality=signal_snapshot,
                now_sec=event.emitted_at_sec,
            )

            if progress is not None:
                is_reliable = (
                    progress.confidence >= self.controller.policy.min_confidence
                    and progress.tracking_quality >= self.controller.policy.tracking_quality_hold_min
                )
                self.metrics.observe_progress(
                    now_sec=event.emitted_at_sec,
                    tracking_quality=progress.tracking_quality,
                    is_reliable=is_reliable,
                )

                playback_status = self.player.get_status()
                self.latency_calibrator.observe_sync(
                    playback_ref_time_sec=playback_status.t_ref_heard_content_sec,
                    user_ref_time_sec=progress.estimated_ref_time_sec,
                    tracking_quality=progress.tracking_quality,
                    stable=progress.stable,
                    active_speaking=progress.active_speaking,
                )

        if progress is None:
            progress = self.progress_estimator.snapshot(
                now_sec=now_sec,
                signal_quality=signal_snapshot,
            )

        playback_status = self.player.get_status()
        decision = self.controller.decide(
            playback=playback_status,
            progress=progress,
            signal_quality=signal_snapshot,
        )

        self._apply_decision(decision, playback_status)
        self._run_auto_tuning(
            now_sec=now_sec,
            progress=progress,
            signal_snapshot=signal_snapshot,
        )
        self._log_event(progress=progress, signal_snapshot=signal_snapshot, decision=decision)

    def _on_audio_frame(self, pcm_bytes: bytes) -> None:
        item = (time.monotonic(), pcm_bytes)
        try:
            self.audio_queue.put_nowait(item)
            self.stats.audio_enqueued += 1
            self.stats.audio_q_high_watermark = max(
                self.stats.audio_q_high_watermark,
                self.audio_queue.qsize(),
            )
        except queue.Full:
            try:
                _ = self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_queue.put_nowait(item)
            except queue.Full:
                pass
            self.stats.audio_dropped += 1

    def _drain_audio_queue(self) -> None:
        while True:
            try:
                observed_at_sec, pcm_bytes = self.audio_queue.get_nowait()
            except queue.Empty:
                break

            self.signal_monitor.feed_pcm16(pcm_bytes, observed_at_sec)
            signal_snapshot = self.signal_monitor.snapshot(observed_at_sec)
            self.latency_calibrator.observe_signal(signal_snapshot)

            should_feed_asr = self._should_feed_asr(signal_snapshot=signal_snapshot, now_sec=observed_at_sec)
            if should_feed_asr:
                self.asr.feed_pcm16(pcm_bytes)
                self.stats.asr_frames_fed += 1
            else:
                self.stats.asr_frames_skipped += 1
                self._maybe_reset_asr_for_silence(signal_snapshot=signal_snapshot, now_sec=observed_at_sec)

    def _should_feed_asr(self, *, signal_snapshot, now_sec: float) -> bool:
        strong_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= self._speech_open_rms
            and signal_snapshot.peak >= self._speech_open_peak
        )
        likely_voice = bool(
            signal_snapshot.speaking_likelihood >= self._speech_open_likelihood
            and signal_snapshot.rms >= self._speech_keep_rms
        )

        keep_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= self._speech_keep_rms
            and signal_snapshot.peak >= self._speech_keep_peak
        ) or bool(
            signal_snapshot.speaking_likelihood >= self._speech_keep_likelihood
            and signal_snapshot.peak >= self._speech_keep_peak
        )

        if strong_voice or likely_voice:
            self._last_human_voice_like_at_sec = float(now_sec)

        gate_should_open = strong_voice or likely_voice
        gate_should_keep = False
        if self._asr_gate_open and self._last_human_voice_like_at_sec > 0.0:
            gate_should_keep = keep_voice or (
                (now_sec - self._last_human_voice_like_at_sec) <= self._speech_tail_hold_sec
            )

        new_gate_state = gate_should_open or gate_should_keep

        if new_gate_state and not self._asr_gate_open:
            self._asr_gate_open = True
            self._asr_gate_last_open_at_sec = float(now_sec)
            self.stats.asr_gate_open_count += 1
            if self.debug:
                print(
                    "[ASR-GATE] open "
                    f"t={now_sec:.3f} rms={signal_snapshot.rms:.5f} "
                    f"peak={signal_snapshot.peak:.5f} "
                    f"vad={signal_snapshot.vad_active} "
                    f"speaking={signal_snapshot.speaking_likelihood:.3f}"
                )
        elif (not new_gate_state) and self._asr_gate_open:
            self._asr_gate_open = False
            self._asr_gate_last_close_at_sec = float(now_sec)
            self.stats.asr_gate_close_count += 1
            if self.debug:
                print(
                    "[ASR-GATE] close "
                    f"t={now_sec:.3f} rms={signal_snapshot.rms:.5f} "
                    f"peak={signal_snapshot.peak:.5f} "
                    f"vad={signal_snapshot.vad_active} "
                    f"speaking={signal_snapshot.speaking_likelihood:.3f}"
                )

        return self._asr_gate_open

    def _maybe_reset_asr_for_silence(self, *, signal_snapshot, now_sec: float) -> None:
        if self._asr_gate_open:
            return

        recently_had_voice = (
            self._last_human_voice_like_at_sec > 0.0
            and (now_sec - self._last_human_voice_like_at_sec) <= self._asr_reset_after_silence_sec
        )
        if recently_had_voice:
            return

        recently_reset = (
            self._last_asr_reset_at_sec > 0.0
            and (now_sec - self._last_asr_reset_at_sec) <= self._asr_reset_cooldown_sec
        )
        if recently_reset:
            return

        very_quiet = (
            signal_snapshot.rms <= self._speech_keep_rms
            and signal_snapshot.peak <= self._speech_keep_peak
            and signal_snapshot.speaking_likelihood <= 0.28
        )
        if not very_quiet:
            return

        try:
            self.asr.reset()
            self._last_asr_reset_at_sec = float(now_sec)
            self.stats.asr_resets_from_silence += 1
            if self.debug:
                print(
                    "[ASR-GATE] reset_stream_for_silence "
                    f"t={now_sec:.3f} rms={signal_snapshot.rms:.5f} "
                    f"peak={signal_snapshot.peak:.5f} "
                    f"speaking={signal_snapshot.speaking_likelihood:.3f}"
                )
        except Exception:
            pass

    def _apply_decision(self, decision, playback_status) -> None:
        action_key = (decision.action.value, decision.reason)
        should_count = action_key != self._last_control_action_key
        self._last_control_action_key = action_key

        if decision.action.value == "hold":
            if playback_status.state != PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("hold", decision.reason, time.monotonic())

        elif decision.action.value == "resume":
            if playback_status.state == PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("resume", decision.reason, time.monotonic())

        elif decision.action.value == "seek" and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=float(decision.target_time_sec),
                    reason=decision.reason,
                )
            )
            if should_count:
                self.metrics.observe_action("seek", decision.reason, time.monotonic())

        elif decision.action.value == "soft_duck" and should_count:
            self.metrics.observe_action("soft_duck", decision.reason, time.monotonic())

        desired_gain = decision.target_gain
        if desired_gain is not None:
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 