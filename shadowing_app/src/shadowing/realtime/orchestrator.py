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
                        "playback_generation": playback_status.generation,
                    },
                    ts_monotonic_sec=time.monotonic(),
                    session_tick=self.stats.ticks,
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
                    now_sec=event.emitted_at_sec,
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
            playback_status=playback_status,
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
            self.asr.feed_pcm16(pcm_bytes)

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
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 0.015:
                self.player.submit_command(
                    PlayerCommand(
                        cmd=PlayerCommandType.SET_GAIN,
                        gain=float(desired_gain),
                        reason=decision.reason,
                    )
                )
                self._last_gain_sent = float(desired_gain)

    def _run_auto_tuning(
        self,
        *,
        now_sec: float,
        progress,
        signal_snapshot,
        playback_status,
    ) -> None:
        if self._device_profile is None:
            return

        updates = self.auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=self.metrics.summary_dict(),
            signal_quality=signal_snapshot,
            progress=progress,
            latency_snapshot=self.latency_calibrator.snapshot(),
            device_profile=asdict(self._device_profile),
        )

        if self.event_logger is not None and updates:
            self.event_logger.log(
                "auto_tune_update",
                {
                    "updates": updates,
                    "best_tracking_quality": self.auto_tuner.state.best_tracking_quality,
                    "speaker_style": self.auto_tuner.state.speaker_style,
                    "environment_style": self.auto_tuner.state.environment_style,
                    "playback_generation": playback_status.generation,
                },
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )

    def _build_initial_device_profile(self, output_sample_rate: int) -> DeviceProfile:
        input_device_name = str(self.device_context.get("input_device_name", "unknown"))
        output_device_name = str(self.device_context.get("output_device_name", "unknown"))
        input_sample_rate = int(self.device_context.get("input_sample_rate", 48000))
        noise_floor_rms = float(self.device_context.get("noise_floor_rms", 0.0025))

        return build_device_profile(
            input_device_name=input_device_name,
            output_device_name=output_device_name,
            input_sample_rate=input_sample_rate,
            output_sample_rate=output_sample_rate,
            noise_floor_rms=noise_floor_rms,
        )

    def _persist_session_profile(self) -> None:
        if self.profile_store is None or self._device_profile is None:
            return

        latency_snapshot = self.latency_calibrator.snapshot()

        updated_profile = DeviceProfileSnapshot(
            input_device_id=self._device_profile.input_device_id,
            output_device_id=self._device_profile.output_device_id,
            input_kind=self._device_profile.input_kind,
            output_kind=self._device_profile.output_kind,
            input_sample_rate=self._device_profile.input_sample_rate,
            output_sample_rate=self._device_profile.output_sample_rate,
            estimated_input_latency_ms=(
                latency_snapshot.estimated_input_latency_ms
                if latency_snapshot is not None
                else self._device_profile.estimated_input_latency_ms
            ),
            estimated_output_latency_ms=(
                latency_snapshot.estimated_output_latency_ms
                if latency_snapshot is not None
                else self._device_profile.estimated_output_latency_ms
            ),
            noise_floor_rms=float(self.signal_monitor.state.noise_floor_rms),
            input_gain_hint=self._device_profile.input_gain_hint,
            reliability_tier=self._device_profile.reliability_tier,
        )

        latency_dict = None
        if latency_snapshot is not None:
            latency_dict = asdict(
                LatencyCalibrationSnapshot(
                    estimated_input_latency_ms=latency_snapshot.estimated_input_latency_ms,
                    estimated_output_latency_ms=latency_snapshot.estimated_output_latency_ms,
                    confidence=latency_snapshot.confidence,
                    calibrated=latency_snapshot.calibrated,
                )
            )

        self.profile_store.update_from_session(
            input_device_id=updated_profile.input_device_id,
            output_device_id=updated_profile.output_device_id,
            device_profile=asdict(updated_profile),
            metrics=self.metrics.summary_dict(),
            latency_calibration=latency_dict,
        )

    def _persist_summary(self) -> None:
        if self.event_logger is None:
            return

        latency_snapshot = self.latency_calibrator.snapshot()
        summary = {
            "lesson_id": self._lesson_id,
            "metrics": self.metrics.summary_dict(),
            "latency_calibration": (
                asdict(
                    LatencyCalibrationSnapshot(
                        estimated_input_latency_ms=latency_snapshot.estimated_input_latency_ms,
                        estimated_output_latency_ms=latency_snapshot.estimated_output_latency_ms,
                        confidence=latency_snapshot.confidence,
                        calibrated=latency_snapshot.calibrated,
                    )
                )
                if latency_snapshot is not None
                else {}
            ),
            "device_profile": asdict(
                DeviceProfileSnapshot(
                    input_device_id=self._device_profile.input_device_id,
                    output_device_id=self._device_profile.output_device_id,
                    input_kind=self._device_profile.input_kind,
                    output_kind=self._device_profile.output_kind,
                    input_sample_rate=self._device_profile.input_sample_rate,
                    output_sample_rate=self._device_profile.output_sample_rate,
                    estimated_input_latency_ms=self._device_profile.estimated_input_latency_ms,
                    estimated_output_latency_ms=self._device_profile.estimated_output_latency_ms,
                    noise_floor_rms=float(self.signal_monitor.state.noise_floor_rms),
                    input_gain_hint=self._device_profile.input_gain_hint,
                    reliability_tier=self._device_profile.reliability_tier,
                )
            ) if self._device_profile is not None else {},
            "stats": asdict(self.stats),
        }

        summary_path = Path(self.event_logger.session_dir) / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.event_logger.log(
            "session_summary",
            summary,
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )

    def _log_event(self, *, progress, signal_snapshot, decision) -> None:
        if self.event_logger is None:
            return

        self.event_logger.log(
            "signal_snapshot",
            {
                "observed_at_sec": signal_snapshot.observed_at_sec,
                "rms": signal_snapshot.rms,
                "peak": signal_snapshot.peak,
                "vad_active": signal_snapshot.vad_active,
                "speaking_likelihood": signal_snapshot.speaking_likelihood,
                "quality_score": signal_snapshot.quality_score,
                "dropout_detected": signal_snapshot.dropout_detected,
                "silence_run_sec": signal_snapshot.silence_run_sec,
            },
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )

        if progress is not None:
            self.event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": progress.estimated_ref_idx,
                    "estimated_ref_time_sec": progress.estimated_ref_time_sec,
                    "tracking_mode": progress.tracking_mode.value,
                    "tracking_quality": progress.tracking_quality,
                    "confidence": progress.confidence,
                    "active_speaking": progress.active_speaking,
                    "user_state": progress.user_state.value,
                    "progress_age_sec": progress.progress_age_sec,
                    "recently_progressed": progress.recently_progressed,
                    "playback_generation": self.player.get_status().generation,
                },
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )

        self.event_logger.log(
            "control_decision",
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "lead_sec": decision.lead_sec,
                "target_time_sec": decision.target_time_sec,
                "target_gain": decision.target_gain,
                "confidence": decision.confidence,
                "playback_generation": self.player.get_status().generation,
            },
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )