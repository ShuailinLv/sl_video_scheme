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
from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.audio_aware_progress_estimator import AudioAwareProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.sync_evidence import SyncEvidenceBuilder
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import AsrEventType, PlaybackState, PlayerCommand, PlayerCommandType, ReferenceMap


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
        reference_audio_store: ReferenceAudioStore | None = None,
        live_audio_matcher=None,
        audio_behavior_classifier=None,
        evidence_fuser=None,
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
        self.reference_audio_store = reference_audio_store
        self.live_audio_matcher = live_audio_matcher
        self.audio_behavior_classifier = audio_behavior_classifier
        self.evidence_fuser = evidence_fuser

        self.audio_queue: queue.Queue[tuple[float, bytes]] = queue.Queue(
            maxsize=max(16, int(audio_queue_maxsize))
        )
        self.loop_interval_sec = float(loop_interval_sec)
        self.debug = bool(debug)

        self.normalizer = TextNormalizer()
        self.tracking_engine = TrackingEngine(self.aligner, debug=debug)
        self.progress_estimator = AudioAwareProgressEstimator()
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self.sync_builder = SyncEvidenceBuilder()

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

        self._speech_open_rms = 0.0085
        self._speech_keep_rms = 0.0052
        self._speech_open_peak = 0.022
        self._speech_keep_peak = 0.014
        self._speech_open_likelihood = 0.50
        self._speech_keep_likelihood = 0.34
        self._speech_tail_hold_sec = 0.70
        self._asr_reset_after_silence_sec = 2.80
        self._asr_reset_cooldown_sec = 1.80

        self._reference_audio_features = None
        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0

        self._bluetooth_long_session_mode = False
        self._stable_lead_samples: list[float] = []
        self._last_stable_lead_rebaseline_at_sec = 0.0

        target_sr = 16000
        try:
            target_sr = int(getattr(self.asr, "sample_rate", 16000))
        except Exception:
            pass
        self._audio_feature_extractor = FrameFeatureExtractor(sample_rate=target_sr)

        _ = asr_event_queue_maxsize

    def configure_runtime(self, runtime_cfg: dict[str, Any]) -> None:
        if "loop_interval_sec" in runtime_cfg:
            self.loop_interval_sec = float(runtime_cfg["loop_interval_sec"])

    def configure_debug(self, debug_cfg: dict[str, Any]) -> None:
        self.debug = bool(debug_cfg.get("enabled", self.debug))
        self.tracking_engine.debug = self.debug

    def start_session(self, lesson_id: str) -> None:
        self._lesson_id = lesson_id
        self._ref_map = self.repo.load_reference_map(lesson_id)
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self._warm_start = {}

        self.tracking_engine.reset(self._ref_map)
        self.progress_estimator.reset(self._ref_map, start_idx=0)
        self.controller.reset()
        self._audio_feature_extractor.reset()

        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        chunks = self.repo.load_audio_chunks(lesson_id)
        self.player.load_chunks(chunks)

        self._session_started_at_sec = time.monotonic()
        self.sync_builder.reset(self._session_started_at_sec)
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

        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0

        self._stable_lead_samples = []
        self._last_stable_lead_rebaseline_at_sec = self._session_started_at_sec

        output_sr = chunks[0].sample_rate if chunks else int(self.device_context.get("output_sample_rate", 44100))
        self._device_profile = self._build_initial_device_profile(output_sr)

        bluetooth_mode = bool(self._device_profile.bluetooth_mode) if self._device_profile is not None else False
        total_duration_sec = float(getattr(self._ref_map, "total_duration_sec", 0.0))
        manual_long_session_flag = bool(self.device_context.get("bluetooth_long_session_mode", False))
        self._bluetooth_long_session_mode = bool(
            bluetooth_mode and (manual_long_session_flag or total_duration_sec >= 1800.0)
        )

        if bluetooth_mode:
            self._speech_open_rms = 0.0072
            self._speech_keep_rms = 0.0045
            self._speech_open_peak = 0.018
            self._speech_keep_peak = 0.011
            self._speech_open_likelihood = 0.42
            self._speech_keep_likelihood = 0.28
            self._speech_tail_hold_sec = 1.20
            self._asr_reset_after_silence_sec = 4.20
            self._asr_reset_cooldown_sec = 2.60
        else:
            self._speech_open_rms = 0.0085
            self._speech_keep_rms = 0.0052
            self._speech_open_peak = 0.022
            self._speech_keep_peak = 0.014
            self._speech_open_likelihood = 0.50
            self._speech_keep_likelihood = 0.34
            self._speech_tail_hold_sec = 0.70
            self._asr_reset_after_silence_sec = 2.80
            self._asr_reset_cooldown_sec = 1.80

        self.latency_calibrator.reset(
            self._device_profile,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=self._bluetooth_long_session_mode,
            now_sec=self._session_started_at_sec,
        )
        self.auto_tuner.reset(
            self._device_profile.reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )

        if self.profile_store is not None and self._device_profile is not None:
            self._warm_start = self.profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
                hostapi_name=self._device_profile.hostapi_name,
                capture_backend=self._device_profile.capture_backend,
                duplex_sample_rate=int(self._device_profile.input_sample_rate),
                reliability_tier=self._device_profile.reliability_tier,
                bluetooth_mode=bluetooth_mode,
            )
            self.auto_tuner.apply_warm_start(
                controller_policy=self.controller.policy,
                player=self.player,
                signal_monitor=self.signal_monitor,
                warm_start=self._warm_start,
            )
            self._apply_latency_warm_start(self._warm_start)

        if self.reference_audio_store is not None and self.live_audio_matcher is not None:
            try:
                self._reference_audio_features = self.reference_audio_store.load(lesson_id)
            except Exception:
                self._reference_audio_features = None

            if self._reference_audio_features is not None:
                self.live_audio_matcher.reset(self._reference_audio_features, self._ref_map)

        if self.audio_behavior_classifier is not None:
            self.audio_behavior_classifier.reset()

        if self.evidence_fuser is not None:
            self.evidence_fuser.reset()

        try:
            self.asr.start()
            self.recorder.start(self._on_audio_frame)
            self.player.start()
        except Exception:
            self._safe_close_startup_resources()
            raise

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
        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.46:
            self.metrics.observe_signal_active(now_sec)

        playback_status = self.player.get_status()
        if playback_status.generation != self._last_generation:
            self._last_generation = playback_status.generation
            self.tracking_engine.on_playback_generation_changed(playback_status.generation)
            self.progress_estimator.on_playback_generation_changed(now_sec)

        raw_events = self.asr.poll_raw_events()
        self.stats.raw_asr_events += len(raw_events)

        last_tracking = None
        for raw_event in raw_events:
            if raw_event.event_type == AsrEventType.PARTIAL:
                self.metrics.observe_asr_partial(raw_event.emitted_at_sec)

            event = self.normalizer.normalize_raw_event(raw_event)
            if event is None:
                continue

            self.stats.normalized_asr_events += 1
            tracking = self.tracking_engine.update(event)
            last_tracking = tracking
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
                    ts_monotonic_sec=tracking.emitted_at_sec,
                    session_tick=self.stats.ticks,
                )

        audio_match = None
        if self.live_audio_matcher is not None:
            progress_hint = (
                None
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.estimated_ref_time_sec)
            )
            text_conf = (
                0.0
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.tracking_quality)
            )
            audio_match = self.live_audio_matcher.snapshot(
                now_sec=now_sec,
                progress_hint_ref_time_sec=progress_hint,
                playback_ref_time_sec=float(playback_status.t_ref_heard_content_sec),
                text_tracking_confidence=text_conf,
            )
            self._latest_audio_match = audio_match

        audio_behavior = None
        if self.audio_behavior_classifier is not None:
            audio_behavior = self.audio_behavior_classifier.update(
                audio_match=audio_match,
                signal_quality=signal_snapshot,
                progress=self.progress_estimator._last_snapshot,
                playback_status=playback_status,
            )
            self._latest_audio_behavior = audio_behavior

        progress = self.progress_estimator.update(
            tracking=last_tracking,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            signal_quality=signal_snapshot,
            now_sec=now_sec,
        )
        if progress is None:
            progress = self.progress_estimator.snapshot(
                now_sec=now_sec,
                signal_quality=signal_snapshot,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
            )

        if progress is not None:
            is_reliable = bool(
                progress.joint_confidence >= self.controller.policy.min_confidence
                and progress.tracking_quality >= self.controller.policy.tracking_quality_hold_min
            )
            self.metrics.observe_progress(
                now_sec=now_sec,
                tracking_quality=progress.tracking_quality,
                is_reliable=is_reliable,
            )

        fusion_evidence = None
        if self.evidence_fuser is not None:
            fusion_evidence = self.evidence_fuser.fuse(
                now_sec=now_sec,
                tracking=last_tracking,
                progress=progress,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
                signal_quality=signal_snapshot,
                playback_status=playback_status,
            )
            self._latest_fusion_evidence = fusion_evidence

        self._maybe_recenter_from_audio(now_sec=now_sec, fusion_evidence=fusion_evidence)

        sync_evidence = self.sync_builder.build(
            now_sec=now_sec,
            signal_quality=signal_snapshot,
            progress=progress,
            fusion_evidence=fusion_evidence,
            bluetooth_mode=self._is_bluetooth_mode(),
            bluetooth_long_session_mode=self._is_bluetooth_long_session_mode(),
        )

        if progress is not None:
            source_mode = str(getattr(progress, "position_source", "text"))
            source_is_text_dominant = source_mode == "text"
            audio_text_disagreement_sec = None
            if audio_match is not None:
                audio_text_disagreement_sec = float(
                    audio_match.estimated_ref_time_sec - progress.estimated_ref_time_sec
                )

            self.latency_calibrator.observe_sync(
                playback_ref_time_sec=playback_status.t_ref_heard_content_sec,
                user_ref_time_sec=progress.estimated_ref_time_sec,
                tracking_quality=progress.tracking_quality,
                stable=progress.stable,
                active_speaking=progress.active_speaking,
                allow_observation=sync_evidence.allow_latency_observation,
                source_is_text_dominant=source_is_text_dominant,
                source_mode=source_mode,
                audio_text_disagreement_sec=audio_text_disagreement_sec,
            )

        self._collect_stable_lead_samples(
            now_sec=now_sec,
            playback_status=playback_status,
            progress=progress,
            sync_evidence=sync_evidence,
        )
        self._maybe_rebaseline_output_offset(now_sec=now_sec)

        playback_status = self.player.get_status()
        decision = self.controller.decide(
            playback=playback_status,
            progress=progress,
            signal_quality=signal_snapshot,
            sync_evidence=sync_evidence,
            fusion_evidence=fusion_evidence,
        )
        self._apply_decision(decision, playback_status)

        self._run_auto_tuning(
            now_sec=now_sec,
            progress=progress,
            signal_snapshot=signal_snapshot,
        )

        self._log_event(
            progress=progress,
            signal_snapshot=signal_snapshot,
            decision=decision,
            sync_evidence=sync_evidence,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            fusion_evidence=fusion_evidence,
        )

    def _apply_latency_warm_start(self, warm_start: dict[str, Any]) -> None:
        latency = dict(warm_start.get("latency", {}))
        if not latency:
            return

        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return

        stable_target_lead_sec = latency.get("stable_target_lead_sec")
        startup_target_lead_sec = latency.get("startup_target_lead_sec")

        if stable_target_lead_sec is not None:
            try:
                snap.baseline_target_lead_sec = float(stable_target_lead_sec)
            except Exception:
                pass

        if "estimated_output_latency_ms" in latency:
            try:
                snap.estimated_output_latency_ms = float(latency["estimated_output_latency_ms"])
            except Exception:
                pass

        if "estimated_input_latency_ms" in latency:
            try:
                snap.estimated_input_latency_ms = float(latency["estimated_input_latency_ms"])
            except Exception:
                pass

        if startup_target_lead_sec is not None and self._is_bluetooth_mode():
            try:
                self.latency_calibrator.target_shadow_lead_sec = float(startup_target_lead_sec)
            except Exception:
                pass

    def _collect_stable_lead_samples(self, *, now_sec: float, playback_status, progress, sync_evidence) -> None:
        if progress is None:
            return
        if not sync_evidence.allow_latency_observation:
            return
        if not progress.active_speaking:
            return
        if progress.tracking_quality < (0.70 if self._is_bluetooth_mode() else 0.76):
            return

        lead_sec = float(playback_status.t_ref_heard_content_sec) - float(progress.estimated_ref_time_sec)
        if abs(lead_sec) > 2.2:
            return

        self._stable_lead_samples.append(float(lead_sec))
        if len(self._stable_lead_samples) > 240:
            self._stable_lead_samples = self._stable_lead_samples[-240:]

    def _maybe_rebaseline_output_offset(self, *, now_sec: float) -> None:
        if self._is_bluetooth_long_session_mode():
            refresh_gap = 180.0
            need_n = 24
            desired = 0.35
        elif self._is_bluetooth_mode():
            refresh_gap = 120.0
            need_n = 20
            desired = 0.28
        else:
            refresh_gap = 240.0
            need_n = 28
            desired = 0.15

        if (now_sec - self._last_stable_lead_rebaseline_at_sec) < refresh_gap:
            return
        if len(self._stable_lead_samples) < need_n:
            return

        vals = sorted(self._stable_lead_samples)
        mid = vals[len(vals) // 2]
        error_sec = float(mid - desired)
        if abs(error_sec) < 0.040:
            self._last_stable_lead_rebaseline_at_sec = now_sec
            self._stable_lead_samples.clear()
            return

        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return

        new_output_offset_sec = max(
            0.0,
            (
                snap.estimated_output_latency_ms
                + snap.runtime_output_drift_ms
                - error_sec * 1000.0
            )
            / 1000.0,
        )

        if hasattr(self.player, "set_output_offset_sec"):
            self.player.set_output_offset_sec(new_output_offset_sec)

        self._last_stable_lead_rebaseline_at_sec = now_sec
        self._stable_lead_samples.clear()

    def _maybe_recenter_from_audio(self, *, now_sec: float, fusion_evidence) -> None:
        if fusion_evidence is None:
            return
        if (now_sec - self._last_audio_recentering_at_sec) < 0.45:
            return
        if not (
            fusion_evidence.should_recenter_aligner_window
            or fusion_evidence.should_widen_reacquire_window
        ):
            return

        ref_idx_hint = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
        if fusion_evidence.should_widen_reacquire_window:
            back, ahead, budget = 18, 40, 8
        else:
            back, ahead, budget = 10, 24, 6

        self.tracking_engine.recenter_from_audio(
            ref_idx_hint=ref_idx_hint,
            search_back=back,
            search_ahead=ahead,
            budget_events=budget,
        )
        self._last_audio_recentering_at_sec = float(now_sec)

        if self.event_logger is not None:
            self.event_logger.log(
                "audio_recentering",
                {
                    "estimated_ref_idx_hint": ref_idx_hint,
                    "estimated_ref_time_sec": float(
                        getattr(fusion_evidence, "estimated_ref_time_sec", 0.0)
                    ),
                    "audio_confidence": float(getattr(fusion_evidence, "audio_confidence", 0.0)),
                    "fused_confidence": float(getattr(fusion_evidence, "fused_confidence", 0.0)),
                    "should_recenter_aligner_window": bool(
                        getattr(fusion_evidence, "should_recenter_aligner_window", False)
                    ),
                    "should_widen_reacquire_window": bool(
                        getattr(fusion_evidence, "should_widen_reacquire_window", False)
                    ),
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )

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

            if self.live_audio_matcher is not None:
                feat_frames = self._audio_feature_extractor.process_pcm16(
                    pcm_bytes,
                    observed_at_sec=observed_at_sec,
                )
                self.live_audio_matcher.feed_features(feat_frames)

            bootstrap_mode = (observed_at_sec - self._session_started_at_sec) <= 4.0
            bluetooth_mode = self._is_bluetooth_mode()

            should_feed_asr = self._should_feed_asr(
                signal_snapshot=signal_snapshot,
                now_sec=observed_at_sec,
                bootstrap_mode=bootstrap_mode,
                bluetooth_mode=bluetooth_mode,
            )

            if should_feed_asr:
                self.asr.feed_pcm16(pcm_bytes)
                self.stats.asr_frames_fed += 1
            else:
                self.stats.asr_frames_skipped += 1
                self._maybe_reset_asr_for_silence(
                    signal_snapshot=signal_snapshot,
                    now_sec=observed_at_sec,
                    bootstrap_mode=bootstrap_mode,
                    bluetooth_mode=bluetooth_mode,
                )

    def _should_feed_asr(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> bool:
        open_rms = 0.0070 if bluetooth_mode else (0.0078 if bootstrap_mode else self._speech_open_rms)
        open_peak = 0.017 if bluetooth_mode else (0.020 if bootstrap_mode else self._speech_open_peak)
        open_likelihood = 0.40 if bluetooth_mode else (0.44 if bootstrap_mode else self._speech_open_likelihood)

        strong_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= open_rms
            and signal_snapshot.peak >= open_peak
        )
        likely_voice = bool(
            signal_snapshot.speaking_likelihood >= open_likelihood
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
        gate_tail_sec = 1.25 if bluetooth_mode else (0.95 if bootstrap_mode else self._speech_tail_hold_sec)

        gate_should_keep = False
        if self._asr_gate_open and self._last_human_voice_like_at_sec > 0.0:
            gate_should_keep = keep_voice or (
                (now_sec - self._last_human_voice_like_at_sec) <= gate_tail_sec
            )

        new_gate_state = gate_should_open or gate_should_keep

        if new_gate_state and not self._asr_gate_open:
            self._asr_gate_open = True
            self._asr_gate_last_open_at_sec = float(now_sec)
            self.stats.asr_gate_open_count += 1
        elif (not new_gate_state) and self._asr_gate_open:
            self._asr_gate_open = False
            self._asr_gate_last_close_at_sec = float(now_sec)
            self.stats.asr_gate_close_count += 1

        return self._asr_gate_open

    def _maybe_reset_asr_for_silence(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> None:
        if self._asr_gate_open or bootstrap_mode or bluetooth_mode:
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

        very_quiet = bool(
            signal_snapshot.rms <= self._speech_keep_rms
            and signal_snapshot.peak <= self._speech_keep_peak
            and signal_snapshot.speaking_likelihood <= 0.18
        )
        if not very_quiet:
            return

        try:
            self.asr.reset()
            self._last_asr_reset_at_sec = float(now_sec)
            self.stats.asr_resets_from_silence += 1
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
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 0.01:
                self.player.submit_command(
                    PlayerCommand(
                        cmd=PlayerCommandType.SET_GAIN,
                        gain=float(desired_gain),
                        reason=decision.reason,
                    )
                )
                self._last_gain_sent = float(desired_gain)

    def _run_auto_tuning(self, *, now_sec: float, progress, signal_snapshot) -> None:
        metrics_summary = self.metrics.summary_dict()
        latency_snapshot = self.latency_calibrator.snapshot()

        self.auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=metrics_summary,
            signal_quality=signal_snapshot,
            progress=progress,
            latency_snapshot=latency_snapshot,
            device_profile=asdict(self._device_profile) if self._device_profile is not None else {},
        )

    def _persist_session_profile(self) -> None:
        if self.profile_store is None or self._device_profile is None:
            return

        latency_snapshot = self.latency_calibrator.snapshot()
        self.profile_store.update_from_session(
            input_device_id=self._device_profile.input_device_id,
            output_device_id=self._device_profile.output_device_id,
            hostapi_name=self._device_profile.hostapi_name,
            capture_backend=self._device_profile.capture_backend,
            duplex_sample_rate=int(self._device_profile.input_sample_rate),
            bluetooth_mode=bool(self._device_profile.bluetooth_mode),
            device_profile=asdict(self._device_profile),
            metrics=self.metrics.summary_dict(),
            latency_calibration=(
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "stable_target_lead_sec": (
                        0.35 if self._bluetooth_long_session_mode
                        else (0.28 if self._is_bluetooth_mode() else 0.15)
                    ),
                    "startup_target_lead_sec": (
                        0.28 if self._is_bluetooth_mode() else 0.15
                    ),
                }
            ),
        )

    def _persist_summary(self) -> None:
        raw_session_dir = str(self.device_context.get("session_dir", "")).strip()
        if not raw_session_dir:
            return

        session_dir = Path(raw_session_dir).expanduser().resolve()
        session_dir.mkdir(parents=True, exist_ok=True)

        latency_snapshot = self.latency_calibrator.snapshot()
        summary = {
            "lesson_id": self._lesson_id,
            "metrics": self.metrics.summary_dict(),
            "stats": asdict(self.stats),
            "device_profile": None if self._device_profile is None else asdict(self._device_profile),
            "device_context": dict(self.device_context),
            "latency_calibration": (
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "baseline_target_lead_sec": latency_snapshot.baseline_target_lead_sec,
                }
            ),
            "controller_policy": asdict(self.controller.policy),
            "latest_audio_match": None if self._latest_audio_match is None else asdict(self._latest_audio_match),
            "latest_audio_behavior": None if self._latest_audio_behavior is None else asdict(self._latest_audio_behavior),
            "latest_fusion_evidence": None if self._latest_fusion_evidence is None else asdict(self._latest_fusion_evidence),
            "bluetooth_long_session_mode": self._bluetooth_long_session_mode,
            "stable_lead_samples_count": len(self._stable_lead_samples),
        }

        (session_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self.event_logger is not None:
            self.event_logger.log(
                "session_summary",
                summary,
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )

    def _log_event(
        self,
        *,
        progress,
        signal_snapshot,
        decision,
        sync_evidence,
        audio_match,
        audio_behavior,
        fusion_evidence,
    ) -> None:
        if self.event_logger is None:
            return

        now_sec = time.monotonic()
        self.event_logger.log(
            "signal_snapshot",
            {
                "rms": signal_snapshot.rms,
                "peak": signal_snapshot.peak,
                "vad_active": signal_snapshot.vad_active,
                "speaking_likelihood": signal_snapshot.speaking_likelihood,
                "quality_score": signal_snapshot.quality_score,
                "dropout_detected": signal_snapshot.dropout_detected,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )

        if progress is not None:
            self.event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": progress.estimated_ref_idx,
                    "estimated_ref_time_sec": progress.estimated_ref_time_sec,
                    "progress_age_sec": progress.progress_age_sec,
                    "tracking_mode": progress.tracking_mode.value,
                    "tracking_quality": progress.tracking_quality,
                    "confidence": progress.confidence,
                    "joint_confidence": progress.joint_confidence,
                    "audio_confidence": progress.audio_confidence,
                    "position_source": progress.position_source,
                    "active_speaking": progress.active_speaking,
                    "recently_progressed": progress.recently_progressed,
                    "user_state": progress.user_state.value,
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )

        self.event_logger.log(
            "sync_evidence",
            {
                "speech_state": sync_evidence.speech_state.value,
                "tracking_state": sync_evidence.tracking_state.value,
                "sync_state": sync_evidence.sync_state.value,
                "speech_confidence": sync_evidence.speech_confidence,
                "tracking_confidence": sync_evidence.tracking_confidence,
                "sync_confidence": sync_evidence.sync_confidence,
                "allow_latency_observation": sync_evidence.allow_latency_observation,
                "allow_seek": sync_evidence.allow_seek,
                "startup_mode": sync_evidence.startup_mode,
                "bluetooth_mode": sync_evidence.bluetooth_mode,
                "bluetooth_long_session_mode": sync_evidence.bluetooth_long_session_mode,
                "audio_confidence": sync_evidence.audio_confidence,
                "still_following_likelihood": sync_evidence.still_following_likelihood,
                "reentry_likelihood": sync_evidence.reentry_likelihood,
                "repeated_likelihood": sync_evidence.repeated_likelihood,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )

        if audio_match is not None:
            self.event_logger.log(
                "audio_match_snapshot",
                asdict(audio_match),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )

        if audio_behavior is not None:
            self.event_logger.log(
                "audio_behavior_snapshot",
                asdict(audio_behavior),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )

        if fusion_evidence is not None:
            self.event_logger.log(
                "fusion_evidence",
                asdict(fusion_evidence),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )

        self.event_logger.log(
            "control_decision",
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "target_time_sec": decision.target_time_sec,
                "lead_sec": decision.lead_sec,
                "target_gain": decision.target_gain,
                "confidence": decision.confidence,
                "aggressiveness": decision.aggressiveness,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )

    def _build_initial_device_profile(self, output_sr: int) -> DeviceProfile:
        input_device_name = str(self.device_context.get("input_device_name", "unknown") or "unknown")
        output_device_name = str(self.device_context.get("output_device_name", "unknown") or "unknown")
        hostapi_name = str(self.device_context.get("hostapi_name", "") or "").strip()
        capture_backend = str(self.device_context.get("capture_backend", "") or "").strip().lower()

        input_device_id = str(self.device_context.get("input_device_id", "") or "").strip()
        output_device_id = str(self.device_context.get("output_device_id", "") or "").strip()

        input_sample_rate = self._safe_int(self.device_context.get("input_sample_rate", 16000), 16000)
        noise_floor_rms = self._safe_float(self.device_context.get("noise_floor_rms", 0.0025), 0.0025)

        return build_device_profile(
            input_device_name=input_device_name,
            output_device_name=output_device_name,
            input_sample_rate=input_sample_rate,
            output_sample_rate=int(output_sr),
            noise_floor_rms=noise_floor_rms,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            input_device_id=input_device_id or None,
            output_device_id=output_device_id or None,
        )

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            out = float(value)
        except Exception:
            return float(default)
        if out != out:
            return float(default)
        return float(out)

    def _is_bluetooth_mode(self) -> bool:
        profile = self._device_profile
        if profile is None:
            return False
        return bool(profile.bluetooth_mode)

    def _is_bluetooth_long_session_mode(self) -> bool:
        return bool(self._bluetooth_long_session_mode)

    def _safe_close_startup_resources(self) -> None:
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.recorder.close()
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
        try:
            self.player.close()
        except Exception:
            pass