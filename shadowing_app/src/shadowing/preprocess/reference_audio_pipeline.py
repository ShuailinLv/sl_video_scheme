from __future__ import annotations


class ReferenceAudioFeaturePipeline:
    def __init__(self, repo, feature_store, analyzer) -> None:
        self.repo = repo
        self.feature_store = feature_store
        self.analyzer = analyzer

    def run(self, lesson_id: str) -> str:
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)
        features = self.analyzer.analyze(
            lesson_id=lesson_id,
            chunks=chunks,
            reference_map=ref_map,
        )
        return self.feature_store.save(lesson_id, features)
