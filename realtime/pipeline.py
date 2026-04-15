from __future__ import annotations

from realtime.detector_engines import D3DetectorEngine, SoSDetectorEngine
from realtime.measurement_builders import (
    CarrierMeasurementBuilder,
    SmoothedPseudorangeMeasurementBuilder,
)
from realtime.output_writer import RealtimeOutputWriter
from realtime.types import DetectorResult, RealtimeEpochPair


class RealtimeSpoofingPipeline:
    """Two-layer realtime skeleton: measurement builders -> detector engines."""

    def __init__(self, output_root: str = "output_rt") -> None:
        self.measurement_builders = [
            CarrierMeasurementBuilder(),
            SmoothedPseudorangeMeasurementBuilder(),
        ]
        self.detector_engines = [
            SoSDetectorEngine(measurement_name="carrier"),
            SoSDetectorEngine(measurement_name="smoothed_pseudorange"),
            D3DetectorEngine(measurement_name="carrier"),
            D3DetectorEngine(measurement_name="smoothed_pseudorange"),
        ]
        self.output_writer = RealtimeOutputWriter(output_root)

    def process_epoch(self, epoch_pair: RealtimeEpochPair) -> list[DetectorResult]:
        results: list[DetectorResult] = []
        for builder in self.measurement_builders:
            frame = builder.build(epoch_pair)
            for engine in self.detector_engines:
                result = engine.process(frame)
                if result is None:
                    continue
                self.output_writer.write_result(result)
                results.append(result)
        return results

