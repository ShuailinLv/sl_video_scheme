from __future__ import annotations

import json
import logging
import os
import re
import time
from http import HTTPStatus
from typing import Any

import dashscope

logger = logging.getLogger(__name__)

_DEFAULT_QWEN_MODEL = "qwen-plus"


def _extract_message_text(response: Any) -> str:
    try:
        choice = response.output.choices[0]
        msg = choice.message
    except Exception:
        msg = response.output.choices[0]["message"]

    content = getattr(msg, "content", None)
    if content is None:
        content = msg.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and "text" in part:
                pieces.append(str(part["text"]))
        return "".join(pieces)

    return str(content)


def _resolve_api_key(api_key: str | None) -> str:
    key = str(api_key or "").strip()
    if key:
        return key

    env_key = str(os.getenv("DASHSCOPE_API_KEY", "")).strip()
    if env_key:
        return env_key

    return ""


def _chat_once(
    *,
    api_key: str | None,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        raise RuntimeError("DashScope API Key 未配置。")

    dashscope.api_key = resolved_api_key

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = dashscope.Generation.call(
        model=str(model or _DEFAULT_QWEN_MODEL).strip(),
        messages=messages,
        result_format="message",
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"DashScope 调用失败: status={response.status_code}, "
            f"code={getattr(response, 'code', None)}, "
            f"message={getattr(response, 'message', None)}"
        )

    text = _extract_message_text(response)
    return text.strip()


def safe_json_loads(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("输入文本为空")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    text_clean = re.sub(r"```json\s*", "", text, flags=re.IGNORECASE)
    text_clean = re.sub(r"```\s*", "", text_clean)

    try:
        data = json.loads(text_clean, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    start = text_clean.find("{")
    end = text_clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text_clean[start : end + 1]
        try:
            data = json.loads(json_str, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            try:
                json_str_fixed = json_str.replace("\r", "").replace("\t", "\\t")
                data = json.loads(json_str_fixed, strict=False)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    raise ValueError("无法解析 JSON")


def _normalize_hotword(term: str) -> str:
    term = str(term or "").strip()
    term = term.replace("\u3000", " ")
    term = re.sub(r"\s+", "", term)
    term = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", term)
    return term


def _is_good_hotword(term: str) -> bool:
    if not term:
        return False
    n = len(term)
    if n < 4 or n > 24:
        return False
    if term[0] in "的了在和与及并就也又把被将呢啊吗呀":
        return False
    if term[-1] in "的了在和与及并就也又呢啊吗呀":
        return False
    if re.fullmatch(r"[A-Za-z]+", term):
        return False
    if re.search(r"[A-Za-z]", term):
        if not re.fullmatch(r"[A-Za-z0-9一-龥]+", term):
            return False
    return True


def _dedupe_hotwords(terms: list[str], max_terms: int) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []

    for term in terms:
        t = _normalize_hotword(term)
        if not _is_good_hotword(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        cleaned.append(t)

    cleaned.sort(key=lambda x: (-len(x), x))

    kept: list[str] = []
    for term in cleaned:
        if any(term in existed for existed in kept if existed != term):
            continue
        kept.append(term)
        if len(kept) >= max_terms:
            break

    return kept


def extract_hotwords_with_qwen(
    *,
    lesson_text: str,
    api_key: str | None = None,
    model: str = _DEFAULT_QWEN_MODEL,
    max_terms: int = 24,
    max_retries: int = 3,
    timeout_sleep_sec: float = 2.0,
) -> list[str]:
    lesson_text = str(lesson_text or "").strip()
    if not lesson_text:
        return []

    clipped_text = lesson_text[:6000]

    system_prompt = (
        "你是一个中文语音识别热词提取器。"
        "你的任务是从演讲稿中提取最适合 ASR 热词注入的短语。"
        "必须只输出 JSON，不要输出任何解释。"
    )

    user_prompt = f"""
请从下面这段中文演讲稿中，提取适合“语音识别热词注入”的短语。
目标：
1. 只保留高质量短语
2. 优先保留专有名词、术语、固定表达、业务短语、容易识别错的实体词
3. 不要保留半截句、残片、无意义短语
4. 不要保留单字、双字碎片
5. 每个短语长度控制在 4~24 个字符
6. 宁少勿滥，最多返回 {max_terms} 个
7. 如果某个短语被更长、更完整的短语包含，则优先保留更完整的那个
8. 输出格式必须是 JSON，格式如下：
{{
  "hotwords": [
    "短语1",
    "短语2"
  ]
}}
演讲稿如下：
\"\"\"
{clipped_text}
\"\"\"
""".strip()

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = _chat_once(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=1200,
            )
            data = safe_json_loads(raw)
            hotwords = data.get("hotwords", [])
            if not isinstance(hotwords, list):
                hotwords = []

            return _dedupe_hotwords([str(x) for x in hotwords], max_terms=max_terms)
        except Exception as e:
            last_error = e
            logger.warning(
                "Qwen 热词提取失败，重试中 (%d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
            if attempt < max_retries - 1:
                time.sleep(timeout_sleep_sec)

    logger.warning("Qwen 热词提取最终失败，返回空列表: %s", last_error)
    return []