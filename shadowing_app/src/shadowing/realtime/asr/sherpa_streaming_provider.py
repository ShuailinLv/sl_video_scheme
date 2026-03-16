from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent

logger = logging.getLogger(__name__)


class SherpaStreamingProvider(ASRProvider):
    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
        debug_feed: bool = False,
        debug_feed_every_n_chunks: int = 20,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.sample_rate = int(sample_rate)
        self.emit_partial_interval_sec = float(emit_partial_interval_sec)
        self.enable_endpoint = bool(enable_endpoint)
        self.debug_feed = bool(debug_feed)
        self.debug_feed_every_n_chunks = max(1, int(debug_feed_every_n_chunks))

        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0

        self._last_partial_log_text = ""
        self._last_summary_log_at = 0.0
        self._summary_interval_sec = 2.5
        self._last_ready_state = False
        self._last_endpoint_state = False

        self._min_meaningful_text_len = int(self.model_config.get("min_meaningful_text_len", 2))
        self._endpoint_min_interval_sec = float(self.model_config.get("endpoint_min_interval_sec", 0.35))
        self._force_reset_after_empty_endpoints = int(
            self.model_config.get("force_reset_after_empty_endpoints", 999999999)
        )
        self._reset_on_empty_endpoint = bool(self.model_config.get("reset_on_empty_endpoint", False))
        self._preserve_stream_on_partial_only = bool(
            self.model_config.get("preserve_stream_on_partial_only", True)
        )

        self._log_hotwords_on_start = bool(self.model_config.get("log_hotwords_on_start", True))
        self._log_hotwords_preview_on_start = bool(
            self.model_config.get("log_hotwords_preview_on_start", True)
        )
        self._hotwords_preview_limit = max(1, int(self.model_config.get("hotwords_preview_limit", 12)))
        self._info_logging = bool(self.model_config.get("info_logging", True))

    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

        hotword_lines = self._parse_hotword_lines(self.hotwords)
        preview = hotword_lines[: self._hotwords_preview_limit]

        if self._info_logging and self._log_hotwords_on_start:
            logger.info(
                "[ASR-HOTWORDS] count=%d score=%.2f",
                len(hotword_lines),
                float(self.model_config.get("hotwords_score", 1.5)),
            )
            if self._log_hotwords_preview_on_start:
                if preview:
                    logger.info("[ASR-HOTWORDS-PREVIEW] %s", " | ".join(preview))
                else:
                    logger.info("[ASR-HOTWORDS-PREVIEW] <empty>")

        if self.debug_feed:
            logger.debug(
                "[ASR-CONFIG] sample_rate=%d emit_partial_interval_sec=%.3f "
                "enable_endpoint=%s min_meaningful_text_len=%d "
                "endpoint_min_interval_sec=%.3f reset_on_empty_endpoint=%s "
                "preserve_stream_on_partial_only=%s",
                self.sample_rate,
                self.emit_partial_interval_sec,
                self.enable_endpoint,
                self._min_meaningful_text_len,
                self._endpoint_min_interval_sec,
                self._reset_on_empty_endpoint,
                self._preserve_stream_on_partial_only,
            )

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or self._recognizer is None or self._stream is None or not pcm_bytes:
            return

        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return

        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        self._feed_counter += 1

        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            abs_mean = float(np.mean(np.abs(audio_f32))) if audio_f32.size else 0.0
            peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
            logger.debug(
                "[ASR-FEED] chunks=%d samples=%d abs_mean=%.5f peak=%.5f",
                self._feed_counter,
                audio_f32.size,
                abs_mean,
                peak,
            )

        self._stream.accept_waveform(self.sample_rate, audio_f32)

        ready_before = self._recognizer.is_ready(self._stream)
        if self.debug_feed and ready_before and not self._last_ready_state:
            logger.debug("[ASR-READY] stream became ready at feed_chunks=%d", self._feed_counter)
        self._last_ready_state = bool(ready_before)

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        self._maybe_log_summary()

    def poll_raw_events(self) -> list[RawAsrEvent]:
        if not self._running or self._recognizer is None or self._stream is None:
            return []

        now = time.monotonic()
        events: list[RawAsrEvent] = []

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        partial_text = self._normalize_text(self._get_result_text())

        if self.debug_feed and partial_text and partial_text != self._last_partial_log_text:
            logger.debug("[ASR-PARTIAL-RAW] %r", partial_text)
            self._last_partial_log_text = partial_text

        if (
            partial_text
            and partial_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.PARTIAL,
                    text=partial_text,
                    emitted_at_sec=now,
                )
            )
            self._last_partial_text = partial_text
            self._last_emit_at = now

        endpoint_hit = self.enable_endpoint and self._is_endpoint()
        if self.debug_feed and endpoint_hit and not self._last_endpoint_state:
            preview = partial_text[:48]
            logger.debug(
                "[ASR-ENDPOINT-HIT] count_next=%d partial_len=%d preview=%r",
                self._endpoint_count + 1,
                len(partial_text),
                preview,
            )
        self._last_endpoint_state = bool(endpoint_hit)

        if endpoint_hit:
            if (now - self._last_endpoint_at) < self._endpoint_min_interval_sec:
                self._maybe_log_summary()
                return events

            self._endpoint_count += 1
            self._last_endpoint_at = now

            final_text = self._normalize_text(self._get_result_text())
            should_emit_final = self._is_meaningful_result(final_text)

            if self.debug_feed and final_text and final_text != self._last_final_text:
                logger.debug("[ASR-FINAL-RAW] %r", final_text)

            if should_emit_final and final_text != self._last_final_text:
                events.append(
                    RawAsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        emitted_at_sec=now,
                    )
                )
                self._last_final_text = final_text
                self._final_emit_count += 1
                self._empty_endpoint_count = 0

                self._reset_stream_state_only()
                self._last_partial_text = ""
                self._last_partial_log_text = ""
                self._last_ready_state = False
                self._last_endpoint_state = False

                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                        "action=reset_after_final",
                        self._endpoint_count,
                        self._final_emit_count,
                        self._last_endpoint_at,
                    )
            else:
                self._empty_endpoint_count += 1

                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT-IGNORED] count=%d empty_count=%d partial_len=%d final_len=%d",
                        self._endpoint_count,
                        self._empty_endpoint_count,
                        len(partial_text),
                        len(final_text),
                    )

                if self._reset_on_empty_endpoint:
                    no_partial_context = not partial_text
                    no_final_context = not final_text

                    if self._preserve_stream_on_partial_only and partial_text and not final_text:
                        no_partial_context = False

                    if (
                        no_partial_context
                        and no_final_context
                        and self._empty_endpoint_count >= self._force_reset_after_empty_endpoints
                    ):
                        self._reset_stream_state_only()
                        self._last_partial_text = ""
                        self._last_partial_log_text = ""
                        self._last_ready_state = False
                        self._last_endpoint_state = False
                        self._empty_endpoint_count = 0

                        if self.debug_feed:
                            logger.debug(
                                "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                                "action=reset_after_empty_endpoint",
                                self._endpoint_count,
                                self._final_emit_count,
                                self._last_endpoint_at,
                            )

        self._maybe_log_summary()
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
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

        if self.debug_feed:
            logger.debug("[ASR-RESET] stream reset by external request")

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

    def _normalize_text(self, text: str) -> str:
        return str(text or "").strip()

    def _is_meaningful_result(self, text: str) -> bool:
        text = self._normalize_text(text)
        if not text:
            return False
        if len(text) < self._min_meaningful_text_len:
            return False
        return True

    def _get_result_text(self) -> str:
        result = self._recognizer.get_result(self._stream)
        if isinstance(result, str):
            return result
        if hasattr(result, "text"):
            return str(result.text or "")
        if isinstance(result, dict):
            return str(result.get("text", ""))
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

    def _parse_hotword_lines(self, hotwords: str) -> list[str]:
        lines = [line.strip() for line in str(hotwords or "").splitlines() if line.strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped

    def _maybe_log_summary(self) -> None:
        if not self.debug_feed:
            return

        now = time.monotonic()
        if (now - self._last_summary_log_at) < self._summary_interval_sec:
            return

        current_text = ""
        if self._recognizer is not None and self._stream is not None:
            current_text = self._get_result_text().strip()

        preview = current_text[:32]
        logger.debug(
            "[ASR-SUMMARY] feeds=%d decodes=%d partials_len=%d finals=%d "
            "endpoints=%d empty_endpoints=%d preview=%r",
            self._feed_counter,
            self._decode_counter,
            len(self._last_partial_text),
            self._final_emit_count,
            self._endpoint_count,
            self._empty_endpoint_count,
            preview,
        )
        self._last_summary_log_at = now

    def _build_recognizer(self):
        import sherpa_onnx

        cfg = self.model_config
        tokens = cfg.get("tokens", "")
        encoder = cfg.get("encoder", "")
        decoder = cfg.get("decoder", "")
        joiner = cfg.get("joiner", "")

        missing = [
            name
            for name, value in (
                ("tokens", tokens),
                ("encoder", encoder),
                ("decoder", decoder),
                ("joiner", joiner),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing sherpa model paths in config: " + ", ".join(missing))

        hotwords = str(self.hotwords or cfg.get("hotwords", "")).strip()
        hotwords_score = float(cfg.get("hotwords_score", 1.5))

        if self.debug_feed:
            hotword_lines = self._parse_hotword_lines(hotwords)
            logger.debug(
                "[ASR-BUILD] hotwords_count=%d hotwords_score=%.2f provider=%s decoding_method=%s",
                len(hotword_lines),
                hotwords_score,
                cfg.get("provider", "cpu"),
                cfg.get("decoding_method", "greedy_search"),
            )
            if hotword_lines:
                logger.debug("[ASR-BUILD-HOTWORDS] %s", " | ".join(hotword_lines[:20]))

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
            hotwords=hotwords,
            hotwords_score=hotwords_score,
        )
        endpoint_kwargs = dict(
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )

        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **hotword_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+hotwords+endpoint")
            return recognizer
        except TypeError as e1:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] hotwords kwargs not accepted, fallback 1: %s", e1)

        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+endpoint")
            return recognizer
        except TypeError as e2:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] endpoint kwargs not accepted, fallback 2: %s", e2)

        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**base_kwargs)
        if self.debug_feed:
            logger.debug("[ASR-BUILD] recognizer_created mode=transducer_basic")
        return recognizer