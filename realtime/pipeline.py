from __future__ import annotations

from typing import Any

from config import config
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
            SoSDetectorEngine(
                measurement_name="carrier",
                threshold=config.SOS_CARRIER_THRESHOLD,
            ),
            SoSDetectorEngine(
                measurement_name="smoothed_pseudorange",
                threshold=config.SOS_SMOOTHED_PSEUDORANGE_THRESHOLD,
            ),
            D3DetectorEngine(
                measurement_name="carrier",
                similarity_threshold=config.D3_CARRIER_SIMILARITY_THRESHOLD,
                min_cluster_size=config.D3_MIN_CLUSTER_SIZE,
            ),
            D3DetectorEngine(
                measurement_name="smoothed_pseudorange",
                similarity_threshold=config.D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD,
                min_cluster_size=config.D3_MIN_CLUSTER_SIZE,
            ),
        ]
        self.output_writer = RealtimeOutputWriter(output_root)
        self._reference_svid: int | None = None
        self._min_sat_count: int = 4

    def set_threshold(self, output_name: str, threshold: float) -> bool:
        for engine in self.detector_engines:
            if engine.output_name == output_name:
                if hasattr(engine, "threshold"):
                    engine.threshold = threshold
                    return True
                elif hasattr(engine, "similarity_threshold"):
                    engine.similarity_threshold = threshold
                    return True
        return False

    def set_reference_svid(self, svid: int) -> None:
        self._reference_svid = svid

    def set_min_sat_count(self, count: int) -> None:
        self._min_sat_count = max(1, count)

    def reset(self) -> None:
        self._reference_svid = None
        self._min_sat_count = 4
        for builder in self.measurement_builders:
            if hasattr(builder, "reset"):
                builder.reset()

    def get_current_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "reference_svid": self._reference_svid,
            "min_sat_count": self._min_sat_count,
            "detectors": {},
        }
        for engine in self.detector_engines:
            threshold = getattr(engine, "threshold", None)
            if threshold is None:
                threshold = getattr(engine, "similarity_threshold", None)
            config["detectors"][engine.output_name] = {
                "threshold": threshold,
                "min_cluster_size": getattr(engine, "min_cluster_size", None),
            }
        return config

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
