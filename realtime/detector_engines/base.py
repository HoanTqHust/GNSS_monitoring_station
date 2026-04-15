from __future__ import annotations

from abc import ABC, abstractmethod

from realtime.types import DetectorResult, MeasurementFrame


class DetectorEngine(ABC):
    """Detector interface over one measurement family."""

    detector_name: str
    measurement_name: str
    output_name: str

    @abstractmethod
    def process(self, frame: MeasurementFrame | None) -> DetectorResult | None:
        raise NotImplementedError

