from __future__ import annotations

from shadowing.preprocess.assembled_reference_loader import AssembledReferenceLoader


class ReferenceAudioFeaturePipeline:
    def __init__(self, repo, feature_store, analyzer) -> None:
        self.repo = repo
        self.feature_store = feature_store
        self.analyzer = analyzer

        base_dir = getattr(repo, "base_dir", None)
        self.assembled_loader = (
            AssembledReferenceLoader(str(base_dir)) if base_dir is not None else None
        )

    def run(self, lesson_id: str) -> str:
        ref_map = self.repo.load_reference_map(lesson_id)

        if self.assembled_loader is not None and self.assembled_loader.exists(lesson_id):
            bundle = self.assembled_loader.load(lesson_id)
            features = self.analyzer.analyze(
                lesson_id=lesson_id,
                chunks=[bundle.audio_chunk],
                reference_map=ref_map,
                segment_records=bundle.segment_records,
            )
            return self.feature_store.save(lesson_id, features)

        chunks = self.repo.load_audio_chunks(lesson_id)
        features = self.analyzer.analyze(
            lesson_id=lesson_id,
            chunks=chunks,
            reference_map=ref_map,
            segment_records=None,
        )
        return self.feature_store.save(lesson_id, features)