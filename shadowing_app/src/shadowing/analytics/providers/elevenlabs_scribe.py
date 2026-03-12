from __future__ import annotations

from shadowing.interfaces.analytics import AnalyticsProvider


class ElevenLabsScribeProvider(AnalyticsProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def analyze_session(
        self,
        lesson_text: str,
        audio_path: str,
        output_dir: str,
    ) -> dict:
        """
        TODO:
        1. 上传整段录音
        2. 请求转写
        3. 结合 lesson_text 做课后评分
        """
        raise NotImplementedError