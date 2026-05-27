import numpy as np

from .common import BladeRFSdr

DAC_NORM_FACTOR = 2048.0


class Transmitter:
    """Transmit IQ samples via bladeRF sync interface."""

    def __init__(self, sdr: BladeRFSdr):
        self.sdr = sdr

    @staticmethod
    def prepare_tx(samples: np.ndarray) -> bytes:
        """Convert complex64 samples → SC16_Q11 int16 bytes (interleaved I/Q)."""
        result = np.empty(len(samples) * 2, dtype=np.int16)
        result[0::2] = np.int16(np.real(samples) * DAC_NORM_FACTOR)
        result[1::2] = np.int16(np.imag(samples) * DAC_NORM_FACTOR)
        return result.tobytes()

    def send(self, samples: np.ndarray, buf_size: int = 8192):
        """Transmit complex64 samples in chunks."""
        n = len(samples)
        pos = 0

        while pos < n:
            chunk = samples[pos : pos + buf_size]
            buf = self.prepare_tx(chunk)
            self.sdr.sdr.sync_tx(buf, len(chunk))
            pos += buf_size

    @staticmethod
    def generate_tone(freq_hz: float, num_samples: int, sample_rate: float) -> np.ndarray:
        """Generate a complex sinusoid at `freq_hz`."""
        t = np.arange(num_samples) / sample_rate
        return np.exp(1j * 2 * np.pi * freq_hz * t)
