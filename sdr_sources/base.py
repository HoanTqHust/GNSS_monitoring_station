from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class SdrSourceSettings:
    sample_rate_hz: float
    center_freq_hz: float
    gain_db: float
    bandwidth_hz: float
    bladerf_device: str
    usrp_args: str
    usrp_channel: int
    usrp_antenna: str
    usrp_stream_args: str
    usrp_recv_timeout_s: float
    usrp_set_bandwidth: bool


class SdrReceiverSource(Protocol):
    def receive_with_raw(self, num_samples: int) -> tuple[np.ndarray, bytes]:
        """Return normalized complex64 samples and SC16_Q11-compatible raw bytes."""

    def close(self) -> None:
        """Release hardware resources."""
