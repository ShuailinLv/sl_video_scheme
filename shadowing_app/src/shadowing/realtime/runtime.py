from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RealtimeRuntimeConfig:
    tick_sleep_sec: float = 0.03


class ShadowingRuntime:
    def __init__(
        self,
        *,
        orchestrator: Any,
        config: RealtimeRuntimeConfig | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or RealtimeRuntimeConfig()
        self._running = False

    def run(self, lesson_id: str) -> None:
        self._running = True
        self.orchestrator.start_session(lesson_id)
        try:
            while self._running:
                self.orchestrator.tick()
                time.sleep(self.config.tick_sleep_sec)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.orchestrator.stop_session()

    def stop(self) -> None:
        self._running = False


RealtimeRuntime = ShadowingRuntime