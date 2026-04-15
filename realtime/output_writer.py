from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from realtime.types import DetectorResult


class RealtimeOutputWriter:
    """Writes detector outputs into separated output_rt folders."""

    def __init__(self, root_dir: str | Path = "output_rt") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def write_result(self, result: DetectorResult) -> Path:
        output_name = result.metadata.get(
            "output_name", f"{result.detector_name}_{result.measurement_name}"
        )
        output_dir = self.root_dir / output_name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "events.jsonl"
        with output_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result), ensure_ascii=True) + "\n")
        return output_file

