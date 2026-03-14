from __future__ import annotations
from shadowing.interfaces.analytics import AnalyticsProvider

class SessionAnalyticsPipeline:    
    def __init__(self, provider: AnalyticsProvider) -> None:        
        self.provider = provider
    def run(self, lesson_text: str, user_audio_path: str, output_dir: str) -> dict:        
        return self.provider.analyze_session(            
                lesson_text=lesson_text,            
                audio_path=user_audio_path,            
                output_dir=output_dir,
                        )