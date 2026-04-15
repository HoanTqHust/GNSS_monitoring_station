from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from realtime.pipeline import RealtimeSpoofingPipeline
from realtime.types import RealtimeEpochPair


@dataclass(frozen=True)
class FakeSatellite:
    svId: int
    gnssId: int
    sigId: int
    prMes: float
    cpMes: float
    locktime: float


@dataclass(frozen=True)
class FakeRawx:
    satData: list[FakeSatellite]


def build_demo_epoch() -> RealtimeEpochPair:
    rawx_1 = FakeRawx(
        satData=[
            FakeSatellite(svId=1, gnssId=0, sigId=0, prMes=20200000.0, cpMes=101.10, locktime=1000),
            FakeSatellite(svId=3, gnssId=0, sigId=0, prMes=21400000.0, cpMes=120.32, locktime=1000),
            FakeSatellite(svId=5, gnssId=0, sigId=0, prMes=22600000.0, cpMes=130.44, locktime=1000),
            FakeSatellite(svId=7, gnssId=0, sigId=0, prMes=23800000.0, cpMes=140.68, locktime=1000),
        ]
    )
    rawx_2 = FakeRawx(
        satData=[
            FakeSatellite(svId=1, gnssId=0, sigId=0, prMes=20200000.4, cpMes=101.14, locktime=1005),
            FakeSatellite(svId=3, gnssId=0, sigId=0, prMes=21400000.9, cpMes=120.41, locktime=1005),
            FakeSatellite(svId=5, gnssId=0, sigId=0, prMes=22600001.0, cpMes=130.55, locktime=1005),
            FakeSatellite(svId=7, gnssId=0, sigId=0, prMes=23800001.1, cpMes=140.78, locktime=1005),
        ]
    )
    return RealtimeEpochPair(
        tow_s=345600.0,
        rawx_1=rawx_1,
        nav_1=None,
        rawx_2=rawx_2,
        nav_2=None,
    )


def main() -> None:
    output_root = Path("output_rt")
    for child in (
        "sos_carrier",
        "sos_smoothed_pseudorange",
        "d3_carrier",
        "d3_smoothed_pseudorange",
    ):
        child_path = output_root / child
        if child_path.exists():
            rmtree(child_path)

    pipeline = RealtimeSpoofingPipeline(output_root=str(output_root))
    results = pipeline.process_epoch(build_demo_epoch())

    print(f"Generated {len(results)} detector outputs:")
    for result in results:
        output_name = result.metadata.get("output_name")
        print(f"- {output_name}: tow={result.tow_s}, score={result.score}, spoofing={result.spoofing}")

    print("\nOutput files:")
    for output_name in (
        "sos_carrier",
        "sos_smoothed_pseudorange",
        "d3_carrier",
        "d3_smoothed_pseudorange",
    ):
        output_file = output_root / output_name / "events.jsonl"
        print(f"- {output_file}: {'OK' if output_file.exists() else 'MISSING'}")


if __name__ == "__main__":
    main()
