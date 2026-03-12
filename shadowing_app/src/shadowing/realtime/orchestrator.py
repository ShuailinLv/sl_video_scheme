from __future__ import annotations

import time
from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import ControlAction


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
        controller: Controller,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller
        self._running = False

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        self.aligner.reset(ref_map)
        self.player.load_chunks(chunks)
        self.asr.start()

        self.recorder.start(self.asr.feed_pcm16)
        self.player.start()
        self._running = True

        while self._running:
            events = self.asr.poll_events()

            for event in events:
                alignment = self.aligner.update(event)
                status = self.player.get_status()
                decision = self.controller.decide(status, alignment)

                if decision.action == ControlAction.HOLD:
                    self.player.hold()
                elif decision.action == ControlAction.RESUME:
                    self.player.resume()
                elif decision.action == ControlAction.SEEK and decision.target_time_sec is not None:
                    self.player.seek(decision.target_time_sec)

            time.sleep(0.03)

    def stop_session(self) -> None:
        self._running = False
        self.recorder.stop()
        self.player.stop()
        self.asr.close()