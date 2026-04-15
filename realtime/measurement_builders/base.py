from __future__ import annotations

from abc import ABC, abstractmethod

from realtime.types import MeasurementFrame, RealtimeEpochPair


class MeasurementBuilder(ABC):
    """Builds one measurement family from a normalized realtime epoch."""

    measurement_name: str

    @abstractmethod
    def build(self, epoch_pair: RealtimeEpochPair) -> MeasurementFrame | None:
        raise NotImplementedError

