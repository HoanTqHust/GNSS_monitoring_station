import unittest

import numpy as np

from config import config
from sdr_sources import SdrSourceSettings, sdr_source_settings_from_config
from sdr_sources.usrp_source import UhdUsrpReceiverSource
from sdr_sources.utils import complex64_to_sc16_q11_bytes


class FakeRXMetadata:
    def __init__(self):
        self.error_code = "none"


class FakeStreamCMD:
    def __init__(self, mode):
        self.mode = mode
        self.stream_now = False


class FakeStreamMode:
    start_cont = "start_cont"
    stop_cont = "stop_cont"


class FakeStreamArgs:
    def __init__(self, cpu_format, otw_format):
        self.cpu_format = cpu_format
        self.otw_format = otw_format
        self.channels = []
        self.args = ""


class FakeTuneRequest:
    def __init__(self, target_freq):
        self.target_freq = target_freq


class FakeRXStreamer:
    def __init__(self):
        self.commands = []
        self.recv_calls = 0

    def get_max_num_samps(self):
        return 3

    def issue_stream_cmd(self, cmd):
        self.commands.append(cmd)

    def recv(self, buffer, metadata, timeout=None):
        del metadata, timeout
        self.recv_calls += 1
        count = min(len(buffer), 2)
        values = np.asarray([0.5 + 0.25j, -0.5 - 0.25j], dtype=np.complex64)
        buffer[:count] = values[:count]
        return count


class FakeMultiUSRP:
    last_instance = None

    def __init__(self, args):
        self.args = args
        self.config_calls = []
        self.streamer = FakeRXStreamer()
        self.stream_args = None
        FakeMultiUSRP.last_instance = self

    def set_rx_rate(self, value, channel):
        self.config_calls.append(("rate", value, channel))

    def set_rx_freq(self, value, channel):
        self.config_calls.append(("freq", value, channel))

    def set_rx_gain(self, value, channel):
        self.config_calls.append(("gain", value, channel))

    def set_rx_bandwidth(self, value, channel):
        self.config_calls.append(("bandwidth", value, channel))

    def set_rx_antenna(self, value, channel):
        self.config_calls.append(("antenna", value, channel))

    def get_rx_stream(self, stream_args):
        self.stream_args = stream_args
        return self.streamer


class FakeUhdModule:
    class usrp:
        MultiUSRP = FakeMultiUSRP
        StreamArgs = FakeStreamArgs

    class types:
        RXMetadata = FakeRXMetadata
        StreamCMD = FakeStreamCMD
        StreamMode = FakeStreamMode
        TuneRequest = FakeTuneRequest


class UsrpSdrSourceTests(unittest.TestCase):
    def setUp(self):
        self.saved_config = {
            "SDR_SAMPLE_RATE": config.SDR_SAMPLE_RATE,
            "SDR_FREQ": config.SDR_FREQ,
            "SDR_GAIN": config.SDR_GAIN,
            "SDR_BANDWIDTH": config.SDR_BANDWIDTH,
            "SDR_DEVICE": config.SDR_DEVICE,
            "SDR_USRP_ARGS": config.SDR_USRP_ARGS,
            "SDR_USRP_CHANNEL": config.SDR_USRP_CHANNEL,
            "SDR_USRP_ANTENNA": config.SDR_USRP_ANTENNA,
            "SDR_USRP_STREAM_ARGS": config.SDR_USRP_STREAM_ARGS,
            "SDR_USRP_RECV_TIMEOUT": config.SDR_USRP_RECV_TIMEOUT,
            "SDR_USRP_SET_BANDWIDTH": config.SDR_USRP_SET_BANDWIDTH,
        }

    def tearDown(self):
        for key, value in self.saved_config.items():
            setattr(config, key, value)

    def _settings(
        self,
        *,
        sample_rate_hz=5_000_000.0,
        center_freq_hz=1_575_420_000.0,
        gain_db=30.0,
        bandwidth_hz=2_500_000.0,
        usrp_args="addr=192.168.5.111",
        usrp_channel=0,
        usrp_antenna="",
        usrp_stream_args="",
        usrp_recv_timeout_s=0.5,
        usrp_set_bandwidth=False,
    ):
        return SdrSourceSettings(
            sample_rate_hz=sample_rate_hz,
            center_freq_hz=center_freq_hz,
            gain_db=gain_db,
            bandwidth_hz=bandwidth_hz,
            bladerf_device="libusb:device=6:3",
            usrp_args=usrp_args,
            usrp_channel=usrp_channel,
            usrp_antenna=usrp_antenna,
            usrp_stream_args=usrp_stream_args,
            usrp_recv_timeout_s=usrp_recv_timeout_s,
            usrp_set_bandwidth=usrp_set_bandwidth,
        )

    def test_complex64_to_sc16_q11_bytes_interleaves_iq(self):
        samples = np.asarray([1.0 + 0.5j, -1.0 - 0.5j], dtype=np.complex64)

        raw = complex64_to_sc16_q11_bytes(samples)
        decoded = np.frombuffer(raw, dtype="<i2")

        self.assertEqual(decoded.tolist(), [2047, 1024, -2047, -1024])

    def test_usrp_source_configures_stream_and_returns_legacy_shape(self):
        settings = self._settings(
            sample_rate_hz=1_000_000.0,
            center_freq_hz=1_575_420_000.0,
            gain_db=30.0,
            bandwidth_hz=500_000.0,
            usrp_args="addr=192.168.5.111",
            usrp_channel=1,
            usrp_antenna="RX2",
            usrp_stream_args="spp=200",
            usrp_recv_timeout_s=0.5,
            usrp_set_bandwidth=True,
        )

        source = UhdUsrpReceiverSource(settings=settings, uhd_module=FakeUhdModule)
        samples, raw_bytes = source.receive_with_raw(4)
        source.close()

        usrp = FakeMultiUSRP.last_instance
        self.assertEqual(usrp.args, "addr=192.168.5.111")
        self.assertIn(("rate", 1_000_000.0, 1), usrp.config_calls)
        freq_calls = [call for call in usrp.config_calls if call[0] == "freq"]
        self.assertEqual(len(freq_calls), 1)
        self.assertIsInstance(freq_calls[0][1], FakeTuneRequest)
        self.assertEqual(freq_calls[0][1].target_freq, 1_575_420_000.0)
        self.assertEqual(freq_calls[0][2], 1)
        self.assertIn(("gain", 30.0, 1), usrp.config_calls)
        self.assertIn(("bandwidth", 500_000.0, 1), usrp.config_calls)
        self.assertIn(("antenna", "RX2", 1), usrp.config_calls)
        self.assertEqual(usrp.stream_args.cpu_format, "fc32")
        self.assertEqual(usrp.stream_args.otw_format, "sc16")
        self.assertEqual(usrp.stream_args.channels, [1])
        self.assertEqual(usrp.stream_args.args, "spp=200")
        self.assertEqual(samples.dtype, np.complex64)
        self.assertEqual(samples.shape, (4,))
        self.assertEqual(len(raw_bytes), 4 * 4)
        self.assertEqual(usrp.streamer.commands[0].mode, "start_cont")
        self.assertEqual(usrp.streamer.commands[-1].mode, "stop_cont")

    def test_usrp_source_skips_bandwidth_by_default(self):
        settings = self._settings(usrp_set_bandwidth=False)

        source = UhdUsrpReceiverSource(settings=settings, uhd_module=FakeUhdModule)
        source.close()

        usrp = FakeMultiUSRP.last_instance
        self.assertNotIn(("bandwidth", 2_500_000.0, 0), usrp.config_calls)

    def test_settings_from_config_maps_both_source_families(self):
        config.SDR_SAMPLE_RATE = 1_000_000.0
        config.SDR_FREQ = 1_575_420_000.0
        config.SDR_GAIN = 20.0
        config.SDR_BANDWIDTH = 500_000.0
        config.SDR_DEVICE = "libusb:device=1:2"
        config.SDR_USRP_ARGS = "addr=192.168.10.2"
        config.SDR_USRP_CHANNEL = 1
        config.SDR_USRP_ANTENNA = "RX2"
        config.SDR_USRP_STREAM_ARGS = "spp=128"
        config.SDR_USRP_RECV_TIMEOUT = 0.25
        config.SDR_USRP_SET_BANDWIDTH = True

        settings = sdr_source_settings_from_config(config)

        self.assertEqual(settings.sample_rate_hz, 1_000_000.0)
        self.assertEqual(settings.center_freq_hz, 1_575_420_000.0)
        self.assertEqual(settings.gain_db, 20.0)
        self.assertEqual(settings.bandwidth_hz, 500_000.0)
        self.assertEqual(settings.bladerf_device, "libusb:device=1:2")
        self.assertEqual(settings.usrp_args, "addr=192.168.10.2")
        self.assertEqual(settings.usrp_channel, 1)
        self.assertEqual(settings.usrp_antenna, "RX2")
        self.assertEqual(settings.usrp_stream_args, "spp=128")
        self.assertEqual(settings.usrp_recv_timeout_s, 0.25)
        self.assertTrue(settings.usrp_set_bandwidth)


if __name__ == "__main__":
    unittest.main()
