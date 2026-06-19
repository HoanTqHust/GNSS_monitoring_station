from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

from .base import SdrSourceSettings
from .utils import validate_positive

LOGGER = logging.getLogger("sdr_sources.bladerf")


class BladeRfReceiverSource:
    def __init__(self, settings: SdrSourceSettings) -> None:
        sdr_root = Path(__file__).resolve().parents[1] / "SDR"
        sdr_root_text = str(sdr_root)
        if sdr_root_text not in sys.path:
            sys.path.insert(0, sdr_root_text)
        from src import BladeRFSdr, Receiver

        validate_positive("SDR_SAMPLE_RATE", settings.sample_rate_hz)
        validate_positive("SDR_BANDWIDTH", settings.bandwidth_hz)
        self._settings = settings
        self._sdr = BladeRFSdr(device_string=settings.bladerf_device)
        self._sdr.config_rx(
            freq=settings.center_freq_hz,
            sr=settings.sample_rate_hz,
            gain=settings.gain_db,
            bw=settings.bandwidth_hz,
        )
        self._receiver = Receiver(self._sdr)
        LOGGER.info(
            "sdr_source_started source=bladerf device=%s freq_hz=%s sample_rate_hz=%s gain_db=%s bandwidth_hz=%s",
            settings.bladerf_device,
            settings.center_freq_hz,
            settings.sample_rate_hz,
            settings.gain_db,
            settings.bandwidth_hz,
        )

    def receive_with_raw(self, num_samples: int) -> tuple[np.ndarray, bytes]:
        return self._receiver.receive_with_raw(num_samples)

    def close(self) -> None:
        self._sdr.close()
