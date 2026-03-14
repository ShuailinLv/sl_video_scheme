from __future__ import annotations

import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent


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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0

        self._last_partial_log_text = ""
        self._last_summary_log_at = 0.0
        self._summary_interval_sec = 2.5
        self._last_ready_state = False
        self._last_endpoint_state = False

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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

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
            print(
                f"[ASR-FEED] chunks={self._feed_counter} samples={audio_f32.size} "
                f"abs_mean={abs_mean:.5f} peak={peak:.5f}"
            )

        self._stream.accept_waveform(self.sample_rate, audio_f32)

        ready_before = self._recognizer.is_ready(self._stream)
        if self.debug_feed and ready_before and not self._last_ready_state:
            print(f"[ASR-READY] stream became ready at feed_chunks={self._feed_counter}")
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

        partial_text = self._get_result_text().strip()

        if self.debug_feed and partial_text and partial_text != self._last_partial_log_text:
            print(f"[ASR-PARTIAL-RAW] {partial_text!r}")
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
            print(
                f"[ASR-ENDPOINT-HIT] count_next={self._endpoint_count + 1} "
                f"partial_len={len(partial_text)} preview={preview!r}"
            )
        self._last_endpoint_state = bool(endpoint_hit)

        if endpoint_hit:
            self._endpoint_count += 1
            self._last_endpoint_at = now
            final_text = self._get_result_text().strip()

            if self.debug_feed and final_text and final_text != self._last_final_text:
                print(f"[ASR-FINAL-RAW] {final_text!r}")

            if final_text and final_text != self._last_final_text:
                events.append(
                    RawAsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        emitted_at_sec=now,
                    )
                )
                self._last_final_text = final_text
                self._final_emit_count += 1

            self._reset_stream_state_only()
            self._last_partial_text = ""
            self._last_partial_log_text = ""
            self._last_ready_state = False
            self._last_endpoint_state = False

            if self.debug_feed:
                print(
                    f"[ASR-ENDPOINT] count={self._endpoint_count} "
                    f"final_count={self._final_emit_count} "
                    f"last_endpoint_at={self._last_endpoint_at:.3f}"
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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

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

    def _maybe_log_summary(self) -> None:
        if not self.debug_feed:
            return

        now = time.monotonic()
        if (now - self._last_summary_log_at) < self._summary_interval_sec:
            return

        current_text = self._get_result_text().strip() if self._recognizer is not None and self._stream is not None else ""
        preview = current_text[:32]
        print(
            f"[ASR-SUMMARY] feeds={self._feed_counter} decodes={self._decode_counter} "
            f"partials_len={len(self._last_partial_text)} finals={self._final_emit_count} "
            f"endpoints={self._endpoint_count} preview={preview!r}"
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
            try:
                return sherpa_onnx.OnlineRecognizer.from_transducer(
                    **base_kwargs,
                    **endpoint_kwargs,
                )
            except TypeError:
                return sherpa_onnx.OnlineRecognizer.from_transducer(**base_kwargs)