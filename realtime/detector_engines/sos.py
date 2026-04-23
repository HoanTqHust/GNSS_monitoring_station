from __future__ import annotations

import numpy as np

from realtime.detector_engines.base import DetectorEngine
from realtime.types import DetectorResult, MeasurementFrame


class SoSDetectorEngine(DetectorEngine):
    """Skeleton SoS detector over one measurement family."""

    detector_name = "sos"

    def __init__(self, measurement_name: str, threshold: float | None = None) -> None:
        self.measurement_name = measurement_name
        self.output_name = f"{self.detector_name}_{measurement_name}"
        self.threshold = threshold

    def process(self, frame: MeasurementFrame | None) -> DetectorResult | None:
        if frame is None or frame.measurement_name != self.measurement_name:
            return None

        values = np.asarray(list(frame.dd_values.values()), dtype=float)
        score = None if values.size == 0 else float(np.mean(np.square(values)))
        # Following the paper/batch reference in this repo, low SoS indicates spoofing
        # because authentic satellites should preserve non-zero DD dispersion.
        spoofing = None if score is None or self.threshold is None else score < self.threshold
        return DetectorResult(
            detector_name=self.detector_name,
            measurement_name=self.measurement_name,
            tow_s=frame.tow_s,
            score=score,
            threshold=self.threshold,
            spoofing=spoofing,
            visible_svids=frame.visible_svids,
            reference_svid=frame.reference_svid,
            metadata={"output_name": self.output_name, **frame.metadata},
        )
