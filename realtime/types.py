from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RealtimeEpochPair:
    """Normalized two-receiver epoch payload consumed by realtime builders."""

    tow_s: float
    rawx_1: Any
    nav_1: Any | None
    rawx_2: Any
    nav_2: Any | None
    received_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )


@dataclass(frozen=True)
class MeasurementFrame:
    """Output of a measurement builder for one epoch/window."""

    measurement_name: str
    tow_s: float
    reference_svid: int | None
    visible_svids: tuple[int, ...]
    dd_values: dict[int, float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectorResult:
    """Output emitted by a detector engine."""

    detector_name: str
    measurement_name: str
    tow_s: float
    score: float | None
    threshold: float | None
    spoofing: bool | None
    visible_svids: tuple[int, ...]
    suspect_svids: tuple[int, ...] = ()
    reference_svid: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

