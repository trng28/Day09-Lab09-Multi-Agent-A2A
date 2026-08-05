from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.coordinator import DisputeWorkflow
from src.coordinator.workflow import write_json


ROOT = Path(__file__).resolve().parents[1]


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_batch(root: Path = ROOT) -> int:
    workflow = DisputeWorkflow(root / "data")
    input_paths = sorted((root / "input").glob("EC_*.json"))
    if not input_paths:
        raise FileNotFoundError(f"No case files found in {root / 'input'}")

    output_dir = root / "output"
    trace_path = root / "trace.jsonl"
    trace_lines: list[str] = []
    for input_path in input_paths:
        output, events = workflow.run(load_case(input_path))
        write_json(output_dir / input_path.name, output)
        trace_lines.extend(json.dumps(event, ensure_ascii=False) for event in events)
    trace_path.write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
    return len(input_paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Olist multi-agent dispute workflow")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project root")
    args = parser.parse_args()
    count = run_batch(args.root.resolve())
    print(f"Generated {count} assessments")


if __name__ == "__main__":
    main()
