from __future__ import annotations

import numpy as np

from .common import BladeRFSdr

BYTES_PER_SAMPLE = 4
ADC_NORM_FACTOR = 2048.0


class Receiver:
    """Receive IQ samples from bladeRF via sync interface."""

    def __init__(self, sdr: BladeRFSdr):
        self.sdr = sdr

    @staticmethod
    def parse_samples(buf: bytearray) -> np.ndarray:
        """Convert SC16_Q11 int16 buffer → complex64 numpy array."""
        raw = np.frombuffer(buf, dtype=np.int16)
        samples = raw[0::2] + 1j * raw[1::2]
        return samples / ADC_NORM_FACTOR

    def receive(self, num_samples: int, buf_size: int = 8192) -> np.ndarray:
        """Receive `num_samples` complex64 samples."""
        samples, _ = self.receive_with_raw(num_samples, buf_size)
        return samples

    def receive_with_raw(self, num_samples: int, buf_size: int = 8192) -> tuple[np.ndarray, bytes]:
        """Receive samples and return both complex64 values and raw SC16_Q11 bytes."""
        buf = bytearray(buf_size * BYTES_PER_SAMPLE)
        x = np.zeros(num_samples, dtype=np.complex64)
        raw_chunks: list[bytes] = []
        n_read = 0

        while n_read < num_samples:
            n = min(buf_size, num_samples - n_read)
            self.sdr.sdr.sync_rx(buf, n)
            raw_chunk = bytes(buf[: n * BYTES_PER_SAMPLE])
            raw_chunks.append(raw_chunk)
            chunk = self.parse_samples(bytearray(raw_chunk))[:n]
            x[n_read : n_read + n] = chunk
            n_read += n

        return x, b"".join(raw_chunks)

    def stream(self, num_samples: int, buf_size: int = 8192):
        """Generator that yields samples in chunks."""
        buf = bytearray(buf_size * BYTES_PER_SAMPLE)
        n_read = 0

        while n_read < num_samples:
            n = min(buf_size, num_samples - n_read)
            self.sdr.sdr.sync_rx(buf, n)
            yield self.parse_samples(buf)[:n]
            n_read += n
