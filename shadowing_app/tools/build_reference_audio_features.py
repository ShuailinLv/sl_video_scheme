from __future__ import annotations

import _bootstrap
import argparse
from pathlib import Path

from shadowing.audio.reference_audio_analyzer import ReferenceAudioAnalyzer
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.infrastructure.lesson_repo import FileLessonRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build reference audio features for a lesson"
    )
    parser.add_argument("--lesson-id", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--frame-size-sec", type=float, default=0.025)
    parser.add_argument("--hop-sec", type=float, default=0.010)
    parser.add_argument("--n-bands", type=int, default=6)
    args = parser.parse_args()

    lesson_base_dir = str(Path(args.lesson_base_dir).expanduser().resolve())
    repo = FileLessonRepository(lesson_base_dir)
    store = ReferenceAudioStore(lesson_base_dir)
    analyzer = ReferenceAudioAnalyzer(
        frame_size_sec=float(args.frame_size_sec),
        hop_sec=float(args.hop_sec),
        n_bands=int(args.n_bands),
    )

    ref_map = repo.load_reference_map(args.lesson_id)
    chunks = repo.load_audio_chunks(args.lesson_id)
    features = analyzer.analyze(
        lesson_id=args.lesson_id,
        chunks=chunks,
        reference_map=ref_map,
    )
    path = store.save(args.lesson_id, features)
    print(path)


if __name__ == "__main__":
    main()