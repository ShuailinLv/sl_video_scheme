from __future__ import annotations

from shadowing.realtime.orchestrator import ShadowingOrchestrator


class ShadowingRuntime:
    def __init__(self, orchestrator: ShadowingOrchestrator) -> None:
        self.orchestrator = orchestrator

    def run(self, lesson_id: str) -> None:
        try:
            self.orchestrator.start_session(lesson_id)
        finally:
            self.orchestrator.stop_session()