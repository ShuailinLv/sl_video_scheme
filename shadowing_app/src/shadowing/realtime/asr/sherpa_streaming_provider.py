from __future__ import annotations

import time
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEvent, AsrEventType
from shadowing.realtime.asr.normalizer import TextNormalizer


class SherpaStreamingProvider(ASRProvider):
    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.normalizer = TextNormalizer()
        self._running = False

    def start(self) -> None:
        # TODO: 初始化 sherpa-onnx recognizer / stream
        self._running = True

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        # TODO: 喂入流式 ASR
        pass

    def poll_events(self) -> list[AsrEvent]:
        # TODO: 从 recognizer 拉 partial/final
        # 这里只给一个骨架
        fake_text = ""
        if not fake_text:
            return []

        normalized = self.normalizer.normalize_text(fake_text)
        pinyin_seq = self.normalizer.to_pinyin_seq(fake_text)

        return [
            AsrEvent(
                event_type=AsrEventType.PARTIAL,
                text=fake_text,
                normalized_text=normalized,
                pinyin_seq=pinyin_seq,
                emitted_at_sec=time.monotonic(),
            )
        ]

    def reset(self) -> None:
        # TODO: reset stream
        pass

    def close(self) -> None:
        self._running = False