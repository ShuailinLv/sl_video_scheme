from __future__ import annotations

import _bootstrap
import argparse
import json
from pathlib import Path

from shadowing.telemetry.session_evaluator import SessionEvaluator


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a recorded shadowing session")
    parser.add_argument("--events-file", type=str, required=True)
    parser.add_argument("--summary-file", type=str, default=None)
    parser.add_argument("--output-json", type=str, default=None)
    args = parser.parse_args()

    evaluator = SessionEvaluator(
        events_file=args.events_file,
        summary_file=args.summary_file,
    )
    result = evaluator.evaluate()
    payload = result.to_dict()

    if args.output_json:
        out_path = Path(args.output_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote evaluation JSON to: {out_path}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()