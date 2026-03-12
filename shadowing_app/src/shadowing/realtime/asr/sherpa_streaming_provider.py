from __future__ import annotations

import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEvent, AsrEventType
from shadowing.realtime.asr.normalizer import TextNormalizer


class SherpaStreamingProvider(ASRProvider):
    """
    本地 streaming ASR provider，兼容不同 sherpa-onnx 版本。

    改进点：
    - feed_pcm16() 直接接收 mono int16 PCM bytes
    - poll_events() 非阻塞返回 partial/final
    - 支持 hotwords / endpoint 参数多级回退
    - 带 ASR-FEED 调试输出
    - 基于 reference_text 的强制最后锚点裁剪
    - 对 trim 结果做缓存去重，避免重复刷日志和重复发相同 partial
    """

    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
        debug_feed: bool = True,
        debug_feed_every_n_chunks: int = 20,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.reference_text = model_config.get("reference_text", "")
        self.sample_rate = sample_rate
        self.emit_partial_interval_sec = emit_partial_interval_sec
        self.enable_endpoint = enable_endpoint

        self.debug_feed = bool(debug_feed)
        self.debug_feed_every_n_chunks = max(1, int(debug_feed_every_n_chunks))

        self.normalizer = TextNormalizer()

        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        # 参考文本锚点
        self._reference_norm = ""
        self._anchor_candidates: list[str] = []

        # trim 去重缓存
        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        # 参数
        self._suffix_overlap_max = int(self.model_config.get("suffix_overlap_max", 24))
        self._tail_trim_min_len = int(self.model_config.get("tail_trim_min_len", 2))
        self._anchor_min_len = int(self.model_config.get("anchor_min_len", 3))
        self._anchor_max_len = int(self.model_config.get("anchor_max_len", 6))

    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        self._build_reference_anchors()

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or self._recognizer is None or self._stream is None:
            return

        if not pcm_bytes:
            return

        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return

        audio_f32 = audio_i16.astype(np.float32) / 32768.0

        self._feed_counter += 1
        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            abs_mean = float(np.mean(np.abs(audio_f32))) if audio_f32.size else 0.0
            peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
            print(
                f"[ASR-FEED] chunks={self._feed_counter} "
                f"samples={audio_f32.size} abs_mean={abs_mean:.5f} peak={peak:.5f}"
            )

        self._stream.accept_waveform(self.sample_rate, audio_f32)

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            print(f"[ASR-FEED] decode_counter={self._decode_counter}")

    def poll_events(self) -> list[AsrEvent]:
        if not self._running or self._recognizer is None or self._stream is None:
            return []

        now = time.monotonic()
        events: list[AsrEvent] = []

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        raw_partial_text = self._get_partial_text()
        processed_text = self._postprocess_partial_text(raw_partial_text) if raw_partial_text else ""

        if (
            processed_text
            and processed_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            normalized = self.normalizer.normalize_text(processed_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(processed_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.PARTIAL,
                        text=processed_text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
                        emitted_at_sec=now,
                    )
                )
                self._last_partial_text = processed_text
                self._last_partial_normalized = normalized
                self._last_emit_at = now

        if self.enable_endpoint and self._is_endpoint():
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

            self._reset_stream_state_only()

        return events

    def reset(self) -> None:
        if self._recognizer is None:
            return

        self._reset_stream_state_only()

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        self._build_reference_anchors()

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

    def _build_reference_anchors(self) -> None:
        self._reference_norm = self.normalizer.normalize_text(self.reference_text or "")
        self._anchor_candidates = []

        if not self._reference_norm:
            return

        max_len = min(self._anchor_max_len, len(self._reference_norm))
        min_len = min(self._anchor_min_len, max_len)

        for n in range(max_len, min_len - 1, -1):
            anchor = self._reference_norm[:n]
            if anchor and anchor not in self._anchor_candidates:
                self._anchor_candidates.append(anchor)

    def _postprocess_partial_text(self, raw_partial_text: str) -> str:
        current_norm = self.normalizer.normalize_text(raw_partial_text)
        if not current_norm:
            return raw_partial_text

        prev_emit_norm = self._last_emitted_normalized
        prev_partial_norm = self._last_partial_normalized

        if current_norm == prev_partial_norm:
            return raw_partial_text

        # 0) 最强优先级：只看 current_norm 本身，若出现第二次参考开头锚点，直接截到最后一次锚点开始
        forced_tail = self._extract_forced_last_anchor_tail(current_norm)
        if forced_tail:
            return self._commit_trim(
                kind="forced_anchor_tail",
                source_norm=current_norm,
                tail_norm=forced_tail,
                prev_emit_norm=prev_emit_norm,
            )

        # 1) 正常顺读：当前是上次已发文本的延长
        if prev_emit_norm and current_norm.startswith(prev_emit_norm):
            appended = current_norm[len(prev_emit_norm):]
            self._last_emitted_normalized = current_norm
            return current_norm if appended else raw_partial_text

        # 2) suffix/prefix overlap 去重
        overlap = self._max_suffix_prefix_overlap(prev_emit_norm, current_norm)
        if overlap > 0:
            new_tail = current_norm[overlap:]
            if len(new_tail) >= self._tail_trim_min_len:
                return self._commit_trim(
                    kind="overlap",
                    source_norm=current_norm,
                    tail_norm=new_tail,
                    prev_emit_norm=prev_emit_norm,
                    extra=f"overlap={overlap}",
                )

        # 3) 默认保留当前 normalized
        self._last_emitted_normalized = current_norm
        return current_norm

    def _commit_trim(
        self,
        kind: str,
        source_norm: str,
        tail_norm: str,
        prev_emit_norm: str,
        extra: str = "",
    ) -> str:
        if (
            source_norm == self._last_trim_source_norm
            and tail_norm == self._last_trim_tail_norm
            and kind == self._last_trim_kind
        ):
            self._last_emitted_normalized = tail_norm
            return tail_norm

        self._last_trim_source_norm = source_norm
        self._last_trim_tail_norm = tail_norm
        self._last_trim_kind = kind
        self._last_emitted_normalized = tail_norm

        msg = (
            f"[ASR-TRIM] {kind}, "
            f"prev_emit_norm={prev_emit_norm!r}, "
            f"current_norm={source_norm!r}, "
            f"tail={tail_norm!r}"
        )
        if extra:
            msg = f"[ASR-TRIM] {extra}, " + msg[len("[ASR-TRIM] ") :]
        print(msg)
        return tail_norm

    def _extract_forced_last_anchor_tail(self, current_norm: str) -> str:
        """
        只依赖 current_norm：
        只要参考开头锚点在 current_norm 中出现了第二次，
        就强制从最后一次锚点开始截断。
        """
        if not current_norm or not self._anchor_candidates:
            return ""

        best_tail = ""
        best_pos = -1

        for anchor in self._anchor_candidates:
            first_pos = current_norm.find(anchor)
            last_pos = current_norm.rfind(anchor)
            if first_pos == -1 or last_pos == -1:
                continue
            if last_pos <= first_pos:
                continue

            tail = current_norm[last_pos:]
            if len(tail) < self._tail_trim_min_len:
                continue

            # 优先取最靠后的重启点
            if last_pos > best_pos:
                best_pos = last_pos
                best_tail = tail

        return best_tail

    def _max_suffix_prefix_overlap(self, prev_norm: str, current_norm: str) -> int:
        if not prev_norm or not current_norm:
            return 0

        max_len = min(len(prev_norm), len(current_norm), self._suffix_overlap_max)
        for k in range(max_len, 0, -1):
            if prev_norm[-k:] == current_norm[:k]:
                return k
        return 0

    def _get_partial_text(self) -> str:
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

    def _is_endpoint(self) -> bool:
        if self._recognizer is None or self._stream is None:
            return False

        if hasattr(self._recognizer, "is_endpoint"):
            try:
                return bool(self._recognizer.is_endpoint(self._stream))
            except TypeError:
                return False

        return False

    def _reset_stream_state_only(self) -> None:
        if self._recognizer is not None:
            self._stream = self._recognizer.create_stream()

    def _build_recognizer(self):
        import sherpa_onnx

        cfg = self.model_config

        tokens = cfg.get("tokens", "")
        encoder = cfg.get("encoder", "")
        decoder = cfg.get("decoder", "")
        joiner = cfg.get("joiner", "")

        missing = []
        if not tokens:
            missing.append("tokens")
        if not encoder:
            missing.append("encoder")
        if not decoder:
            missing.append("decoder")
        if not joiner:
            missing.append("joiner")

        if missing:
            raise ValueError(
                "Missing sherpa model paths in config: "
                + ", ".join(missing)
                + ". Please set SHERPA_TOKENS / SHERPA_ENCODER / SHERPA_DECODER / SHERPA_JOINER."
            )

        base_kwargs = dict(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=cfg.get("num_threads", 2),
            sample_rate=self.sample_rate,
            feature_dim=cfg.get("feature_dim", 80),
            decoding_method=cfg.get("decoding_method", "greedy_search"),
            provider=cfg.get("provider", "cpu"),
        )

        hotword_kwargs = dict(
            hotwords=self.hotwords or cfg.get("hotwords", ""),
            hotwords_score=cfg.get("hotwords_score", 1.5),
        )

        endpoint_kwargs = dict(
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **hotword_kwargs,
                **endpoint_kwargs,
            )
        except TypeError:
            pass

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **endpoint_kwargs,
            )
        except TypeError:
            pass

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
            )
        except TypeError as e:
            raise RuntimeError(
                "Failed to build sherpa recognizer. "
                "Your installed sherpa-onnx version uses a different "
                "OnlineRecognizer.from_transducer() signature. "
                "Please inspect the local sherpa_onnx Python API."
            ) from e