from __future__ import annotations

import queue
import threading
import time

from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import (
    AsrEvent,
    ControlAction,
    PlayerCommand,
    PlayerCommandType,
)


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
        controller: Controller,
        audio_queue_maxsize: int = 6,
        asr_event_queue_maxsize: int = 32,
        loop_interval_sec: float = 0.03,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = loop_interval_sec
        self._running = False
        self._asr_thread: threading.Thread | None = None
        self._last_alignment = None

        self._debug_enabled = False
        self._debug_heartbeat_sec = 1.0
        self._debug_print_asr = True
        self._debug_print_alignment = True
        self._debug_print_decision = True
        self._debug_print_player_status = True
        self._debug_print_reference_head = True
        self._last_heartbeat_at = 0.0

        self._pure_playback = False

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self._debug_heartbeat_sec = float(debug_cfg.get("heartbeat_sec", 1.0))
        self._debug_print_asr = bool(debug_cfg.get("print_asr", True))
        self._debug_print_alignment = bool(debug_cfg.get("print_alignment", True))
        self._debug_print_decision = bool(debug_cfg.get("print_decision", True))
        self._debug_print_player_status = bool(debug_cfg.get("print_player_status", True))
        self._debug_print_reference_head = bool(debug_cfg.get("print_reference_head", True))

    def configure_runtime(self, runtime_cfg: dict) -> None:
        self._pure_playback = bool(runtime_cfg.get("pure_playback", False))

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        if hasattr(self.controller, "total_duration_sec"):
            try:
                self.controller.total_duration_sec = ref_map.total_duration_sec
            except Exception:
                pass

        if hasattr(self.player, "sample_rate"):
            try:
                self.player.sample_rate = int(manifest.sample_rate_out)
            except Exception:
                pass

        self.aligner.reset(ref_map)

        if self._debug_enabled and self._debug_print_reference_head:
            head = "".join(tok.char for tok in ref_map.tokens[:20])
            head_py = [tok.pinyin for tok in ref_map.tokens[:10]]
            print(f"[REF] total_tokens={len(ref_map.tokens)} total_duration={ref_map.total_duration_sec:.3f}")
            print(f"[REF] head_chars={head!r}")
            print(f"[REF] head_pinyin={head_py}")

        self.player.load_chunks(chunks)

        self._running = True

        if not self._pure_playback:
            hotwords = manifest.lesson_text

            if hasattr(self.asr, "hotwords"):
                try:
                    self.asr.hotwords = hotwords
                except Exception:
                    pass

            # 关键新增：把参考全文也注入 ASR，供 anchor trimming 使用
            if hasattr(self.asr, "reference_text"):
                try:
                    self.asr.reference_text = manifest.lesson_text
                except Exception:
                    pass

            self.asr.start()
            self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
            self._asr_thread.start()
            self.recorder.start(self._on_audio_frame)

        self.player.start()

        if self._pure_playback:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=1.0,
                    reason="pure_playback_gain",
                )
            )

        self._last_heartbeat_at = time.monotonic()

        while self._running:
            self._control_tick()
            self._debug_heartbeat()
            time.sleep(self.loop_interval_sec)

    def stop_session(self) -> None:
        self._running = False

        if not self._pure_playback:
            try:
                self.recorder.stop()
            except Exception:
                pass

            try:
                self.asr.close()
            except Exception:
                pass

        try:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason="session_stop")
            )
            self.player.stop()
        except Exception:
            pass

    def _on_audio_frame(self, pcm: bytes) -> None:
        try:
            self.audio_frame_queue.put_nowait(pcm)
        except queue.Full:
            try:
                _ = self.audio_frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_frame_queue.put_nowait(pcm)
            except queue.Full:
                pass

    def _asr_worker(self) -> None:
        while self._running and not self._pure_playback:
            try:
                pcm = self.audio_frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            self.asr.feed_pcm16(pcm)
            events = self.asr.poll_events()

            for event in events:
                try:
                    self.asr_event_queue.put_nowait(event)
                except queue.Full:
                    try:
                        _ = self.asr_event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.asr_event_queue.put_nowait(event)
                    except queue.Full:
                        pass

    def _control_tick(self) -> None:
        latest_alignment = self._last_alignment

        if self._debug_enabled:
            print(
                f"[DBG] tick_start "
                f"cached_alignment={type(self._last_alignment).__name__} "
                f"value={self._last_alignment}"
            )

        while not self._pure_playback:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            if hasattr(self.controller, "note_asr_event"):
                try:
                    self.controller.note_asr_event(event)
                except Exception:
                    pass

            if self._debug_enabled and self._debug_print_asr:
                self._debug_print_asr_event(event)

            latest_alignment = self.aligner.update(event)

            if self._debug_enabled:
                print(
                    f"[DBG] aligner_return "
                    f"type={type(latest_alignment).__name__} "
                    f"value={latest_alignment}"
                )

            if latest_alignment is not None:
                self._last_alignment = latest_alignment
                if self._debug_enabled:
                    print(
                        f"[DBG] cache_alignment_updated "
                        f"type={type(self._last_alignment).__name__} "
                        f"value={self._last_alignment}"
                    )

            if self._debug_enabled and self._debug_print_alignment and latest_alignment is not None:
                self._debug_print_alignment_result(latest_alignment)

        status = self.player.get_status()

        if self._debug_enabled:
            print(
                f"[DBG] before_decide "
                f"latest_alignment_type={type(latest_alignment).__name__} "
                f"latest_alignment={latest_alignment}"
            )

        if status.state.value == "finished":
            if self._debug_enabled:
                print("[SYSTEM] player finished, stopping orchestrator.")
            self._running = False
            return

        if self._pure_playback:
            if self._debug_enabled and self._debug_print_decision:
                print(
                    "[CTRL] action=noop "
                    "reason=pure_playback "
                    "lead=None target=None gain=1.00 "
                    f"player_state={status.state.value}"
                )
            return

        decision = self.controller.decide(status, latest_alignment)

        if decision.target_gain is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=decision.target_gain,
                    reason="adaptive_ducking",
                )
            )

        if self._debug_enabled and self._debug_print_decision:
            self._debug_print_decision_result(status, latest_alignment, decision)

        if decision.action == ControlAction.HOLD:
            if hasattr(self.controller, "note_hold"):
                try:
                    self.controller.note_hold()
                except Exception:
                    pass

            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
            )

        elif decision.action == ControlAction.RESUME:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
            )

        elif decision.action == ControlAction.SEEK and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=decision.target_time_sec,
                    reason=decision.reason,
                )
            )

        elif decision.action == ControlAction.STOP:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason=decision.reason)
            )
            self._running = False
            

    def _debug_heartbeat(self) -> None:
        if not self._debug_enabled or not self._debug_print_player_status:
            return

        now = time.monotonic()
        if (now - self._last_heartbeat_at) < self._debug_heartbeat_sec:
            return

        status = self.player.get_status()
        print(
            "[PLAYER] "
            f"state={status.state.value} "
            f"chunk={status.chunk_id} "
            f"frame={status.frame_index} "
            f"t_sched={status.t_ref_sched_sec:.3f} "
            f"t_heard={status.t_ref_heard_sec:.3f}"
        )
        self._last_heartbeat_at = now

    def _debug_print_asr_event(self, event: AsrEvent) -> None:
        print(
            "[ASR] "
            f"type={event.event_type.value} "
            f"text={event.text!r} "
            f"norm={event.normalized_text!r} "
            f"py={event.pinyin_seq}"
        )

    def _debug_print_alignment_result(self, alignment) -> None:
        print(
            "[ALIGN] "
            f"committed={alignment.committed_ref_idx} "
            f"candidate={alignment.candidate_ref_idx} "
            f"t_user={alignment.ref_time_sec:.3f} "
            f"conf={alignment.confidence:.3f} "
            f"stable={alignment.stable} "
            f"matched={alignment.matched_text!r}"
        )

    def _debug_print_decision_result(self, status, alignment, decision) -> None:
        lead = None
        if alignment is not None:
            lead = status.t_ref_heard_sec - alignment.ref_time_sec

        lead_str = "None" if lead is None else f"{lead:.3f}"
        target_str = "None" if decision.target_time_sec is None else f"{decision.target_time_sec:.3f}"
        gain_str = "None" if decision.target_gain is None else f"{decision.target_gain:.2f}"

        print(
            "[CTRL] "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"target={target_str} "
            f"gain={gain_str} "
            f"player_state={status.state.value}"
        )