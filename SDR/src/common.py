import os
from bladerf import _bladerf

LIBBLADERF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "bladeRF", "host", "build", "output"
)
if os.path.exists(LIBBLADERF_PATH):
    os.environ["LD_LIBRARY_PATH"] = LIBBLADERF_PATH + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")


class BladeRFSdr:
    """BladeRF SDR wrapper — manages device init, RX/TX channels, and sync config."""

    def __init__(self, device_string="libusb:device=6:3"):
        self.sdr = _bladerf.BladeRF(device_string)
        self.rx_ch = self.sdr.Channel(_bladerf.CHANNEL_RX(0))
        self.tx_ch = self.sdr.Channel(_bladerf.CHANNEL_TX(0))
        self._rx_enabled = False
        self._tx_enabled = False

    def config_rx(self, freq=1e9, sr=10e6, gain=50, bw=None):
        """Configure RX channel: frequency (Hz), sample_rate (Hz), gain (dB), bandwidth (Hz)."""
        self.rx_ch.frequency = int(freq)
        self.rx_ch.sample_rate = int(sr)
        self.rx_ch.bandwidth = int(bw if bw else sr / 2)
        self.rx_ch.gain_mode = _bladerf.GainMode.Manual
        self.rx_ch.gain = gain

        self.sdr.sync_config(
            layout=_bladerf.ChannelLayout.RX_X1,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=16,
            buffer_size=8192,
            num_transfers=8,
            stream_timeout=3500,
        )
        self.rx_ch.enable = True
        self._rx_enabled = True

    def config_tx(self, freq=1e9, sr=10e6, gain=-6, bw=None):
        """Configure TX channel: frequency (Hz), sample_rate (Hz), gain (dB), bandwidth (Hz)."""
        self.tx_ch.frequency = int(freq)
        self.tx_ch.sample_rate = int(sr)
        self.tx_ch.bandwidth = int(bw if bw else sr / 2)
        try:
            self.tx_ch.gain = gain
        except Exception:
            pass  # bladeRF1 TX may not support gain control

        self.sdr.sync_config(
            layout=_bladerf.ChannelLayout.TX_X1,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=16,
            buffer_size=8192,
            num_transfers=8,
            stream_timeout=3500,
        )
        self.tx_ch.enable = True
        self._tx_enabled = True

    def close(self):
        if self._rx_enabled:
            self.rx_ch.enable = False
            self._rx_enabled = False
        if self._tx_enabled:
            self.tx_ch.enable = False
            self._tx_enabled = False
        self.sdr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
