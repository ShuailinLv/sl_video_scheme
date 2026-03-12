from __future__ import annotations

import base64
import re
from pathlib import Path

import httpx
from pypinyin import lazy_pinyin

from shadowing.interfaces.tts import TTSProvider
from shadowing.preprocess.reference_builder import ReferenceBuilder
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):
    """
    使用 ElevenLabs /v1/text-to-speech/{voice_id}/with-timestamps
    生成分块音频和字符级时间戳。
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "mp3_44100_128",
        timeout_sec: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = timeout_sec

        self.reference_builder = ReferenceBuilder()

    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        chunks_dir = output_path / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        clauses = self._split_text(text)
        if not clauses:
            raise ValueError("No valid clauses found after splitting input text.")

        all_chars: list[str] = []
        all_pinyins: list[str] = []
        all_starts: list[float] = []
        all_ends: list[float] = []
        all_sentence_ids: list[int] = []
        all_clause_ids: list[int] = []

        chunk_paths: list[str] = []
        global_time_offset = 0.0
        sentence_id = 0

        with httpx.Client(timeout=self.timeout_sec) as client:
            for clause_id, clause_text in enumerate(clauses):
                resp = self._request_tts_with_timestamps(client, clause_text)
                audio_bytes = base64.b64decode(resp["audio_base64"])

                chunk_file = chunks_dir / f"{clause_id:04d}.mp3"
                chunk_file.write_bytes(audio_bytes)
                chunk_paths.append(str(chunk_file))

                # 关键修复：
                # 必须优先使用原始 alignment，而不是 normalized_alignment
                alignment = resp.get("alignment") or resp.get("normalized_alignment")
                if not alignment:
                    raise ValueError(f"No alignment returned for clause {clause_id}: {clause_text!r}")

                chars = alignment["characters"]
                starts = alignment["character_start_times_seconds"]
                ends = alignment["character_end_times_seconds"]

                if not (len(chars) == len(starts) == len(ends)):
                    raise ValueError(
                        f"Alignment length mismatch in clause {clause_id}: "
                        f"{len(chars)=}, {len(starts)=}, {len(ends)=}"
                    )

                # 关键修复：
                # chars 应该是中文字符；拼音按中文字符逐个生成
                pinyins = []
                for ch in chars:
                    if ch.strip():
                        py_list = lazy_pinyin(ch)
                        pinyins.append(py_list[0] if py_list else ch)
                    else:
                        pinyins.append("")

                for ch, py, ts, te in zip(chars, pinyins, starts, ends, strict=True):
                    all_chars.append(ch)
                    all_pinyins.append(py)
                    all_starts.append(global_time_offset + float(ts))
                    all_ends.append(global_time_offset + float(te))
                    all_sentence_ids.append(sentence_id)
                    all_clause_ids.append(clause_id)

                if ends:
                    global_time_offset += float(ends[-1])

                if clause_text and clause_text[-1] in "。！？!?":
                    sentence_id += 1

        ref_map = self.reference_builder.build(
            lesson_id=lesson_id,
            chars=all_chars,
            pinyins=all_pinyins,
            starts=all_starts,
            ends=all_ends,
            sentence_ids=all_sentence_ids,
            clause_ids=all_clause_ids,
        )

        manifest = LessonManifest(
            lesson_id=lesson_id,
            lesson_text=text,
            sample_rate_out=44100,
            chunk_paths=chunk_paths,
            reference_map_path=str(output_path / "reference_map.json"),
        )

        return manifest, ref_map

    def _request_tts_with_timestamps(self, client: httpx.Client, text: str) -> dict:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "output_format": self.output_format,
        }

        response = client.post(url, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"ElevenLabs TTS failed: status={response.status_code}, body={response.text}"
            ) from e

        data = response.json()
        if "audio_base64" not in data:
            raise RuntimeError(f"ElevenLabs response missing audio_base64: {data}")

        return data

    def _split_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []

        parts = re.split(r"(?<=[。！？!?])", text)
        parts = [p.strip() for p in parts if p.strip()]

        clauses: list[str] = []
        for part in parts:
            if len(part) <= 120:
                clauses.append(part)
                continue

            subparts = re.split(r"(?<=[，、；,;])", part)
            buf = ""
            for sp in subparts:
                sp = sp.strip()
                if not sp:
                    continue
                if len(buf) + len(sp) <= 120:
                    buf += sp
                else:
                    if buf:
                        clauses.append(buf)
                    buf = sp
            if buf:
                clauses.append(buf)

        return clauses