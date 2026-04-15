from __future__ import annotations

from itertools import combinations

from realtime.detector_engines.base import DetectorEngine
from realtime.types import DetectorResult, MeasurementFrame


class D3DetectorEngine(DetectorEngine):
    """Skeleton D3 detector over one measurement family."""

    detector_name = "d3"

    def __init__(
        self,
        measurement_name: str,
        similarity_threshold: float | None = None,
        min_cluster_size: int = 3,
    ) -> None:
        self.measurement_name = measurement_name
        self.output_name = f"{self.detector_name}_{measurement_name}"
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size

    def process(self, frame: MeasurementFrame | None) -> DetectorResult | None:
        if frame is None or frame.measurement_name != self.measurement_name:
            return None

        suspect_svids: set[int] = set()
        candidate_items = list(frame.dd_values.items())
        if self.similarity_threshold is not None:
            for (svid_a, value_a), (svid_b, value_b) in combinations(candidate_items, 2):
                if abs(value_a - value_b) <= self.similarity_threshold:
                    suspect_svids.add(svid_a)
                    suspect_svids.add(svid_b)

        score = float(len(suspect_svids))
        spoofing = None
        if self.similarity_threshold is not None:
            spoofing = len(suspect_svids) >= self.min_cluster_size

        return DetectorResult(
            detector_name=self.detector_name,
            measurement_name=self.measurement_name,
            tow_s=frame.tow_s,
            score=score,
            threshold=self.similarity_threshold,
            spoofing=spoofing,
            visible_svids=frame.visible_svids,
            suspect_svids=tuple(sorted(suspect_svids)),
            reference_svid=frame.reference_svid,
            metadata={
                "output_name": self.output_name,
                "min_cluster_size": self.min_cluster_size,
                **frame.metadata,
            },
        )

