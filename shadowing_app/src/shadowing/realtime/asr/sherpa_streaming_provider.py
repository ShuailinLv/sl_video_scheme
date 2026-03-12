from __future__ import annotations

import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEvent, AsrEventType
from shadowing.realtime.asr.normalizer import TextNormalizer


class SherpaStreamingProvider(ASRProvider):
    """
    第一版目标：
    - 本地 streaming recognizer
    - 支持 hotwords 字段
    - feed_pcm16() 可直接接收 recorder 输出
    - poll_events() 非阻塞返回 partial/final

    注意：
    sherpa-onnx 的 Python API 在不同版本间会有些字段差异。
    你需要把 _build_recognizer() 里的配置字段按本机版本微调一次。
    """

    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.sample_rate = sample_rate
        self.emit_partial_interval_sec = emit_partial_interval_sec
        self.enable_endpoint = enable_endpoint

        self.normalizer = TextNormalizer()

        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        """
        输入:
            little-endian int16 PCM bytes, mono, 16k
        内部转成 float32 [-1, 1] 再 accept_waveform
        """
        if not self._running or self._recognizer is None or self._stream is None:
            return

        if not pcm_bytes:
            return

        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return

        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        self._stream.accept_waveform(self.sample_rate, audio_f32)

        # 尽量把当前可解码内容推进一遍
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)

    def poll_events(self) -> list[AsrEvent]:
        """
        非阻塞获取 ASR 事件。
        只返回“相对上次有变化”的事件，避免控制环被重复 partial 淹没。
        """
        if not self._running or self._recognizer is None or self._stream is None:
            return []

        now = time.monotonic()
        events: list[AsrEvent] = []

        # 尽量继续推进解码
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)

        # 1) partial
        partial_text = self._get_partial_text()
        if (
            partial_text
            and partial_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            normalized = self.normalizer.normalize_text(partial_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(partial_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.PARTIAL,
                        text=partial_text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
                        emitted_at_sec=now,
                    )
                )
                self._last_partial_text = partial_text
                self._last_emit_at = now

        # 2) endpoint/final
        if self.enable_endpoint and self._recognizer.is_endpoint(self._stream):
            final_text = self._get_final_text()
            if final_text and final_text != self._last_final_text:
                normalized = self.normalizer.normalize_text(final_text)
                pinyin_seq = self.normalizer.to_pinyin_seq(final_text)

                if normalized:
                    events.append(
                        AsrEvent(
                            event_type=AsrEventType.FINAL,
                            text=final_text,
                            normalized_text=normalized,
                            pinyin_seq=pinyin_seq,
                            emitted_at_sec=now,
                        )
                    )
                    self._last_final_text = final_text

            # endpoint 后重置 stream，避免上下文无限拖长
            self._stream = self._recognizer.create_stream()

        return events

    def reset(self) -> None:
        if self._recognizer is None:
            return

        self._stream = self._recognizer.create_stream()
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

    def _get_partial_text(self) -> str:
        """
        兼容不同 sherpa-onnx 版本常见写法。
        """
        result = self._recognizer.get_result(self._stream)

        if isinstance(result, str):
            return result.strip()

        if hasattr(result, "text"):
            return (result.text or "").strip()

        if isinstance(result, dict):
            return str(result.get("text", "")).strip()

        return ""

    def _get_final_text(self) -> str:
        result = self._recognizer.get_result(self._stream)

        if isinstance(result, str):
            return result.strip()

        if hasattr(result, "text"):
            return (result.text or "").strip()

        if isinstance(result, dict):
            return str(result.get("text", "")).strip()

        return ""

    def _build_recognizer(self):
        """
        你需要按本机安装的 sherpa-onnx 版本把这里对一下字段名。
        下面是“streaming transducer/zipformer”风格的骨架。

        model_config 示例建议：
        {
            "tokens": ".../tokens.txt",
            "encoder": ".../encoder-epoch-99-avg-1.int8.onnx",
            "decoder": ".../decoder-epoch-99-avg-1.onnx",
            "joiner": ".../joiner-epoch-99-avg-1.int8.onnx",
            "num_threads": 2,
            "provider": "cpu",
            "rule1_min_trailing_silence": 10.0,
            "rule2_min_trailing_silence": 10.0,
            "rule3_min_utterance_length": 60.0,
        }
        """
        import sherpa_onnx

        cfg = self.model_config

        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=cfg["tokens"],
            encoder=cfg["encoder"],
            decoder=cfg["decoder"],
            joiner=cfg["joiner"],
            num_threads=cfg.get("num_threads", 2),
            sample_rate=self.sample_rate,
            feature_dim=cfg.get("feature_dim", 80),
            decoding_method=cfg.get("decoding_method", "greedy_search"),
            provider=cfg.get("provider", "cpu"),
            hotwords=self.hotwords or cfg.get("hotwords", ""),
            hotwords_score=cfg.get("hotwords_score", 1.5),
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )
        return recognizer