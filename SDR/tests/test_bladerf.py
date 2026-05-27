import sys
import numpy as np

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Receiver, Transmitter

SR = 10e6


def test_device_info():
    with BladeRFSdr() as sdr:
        assert sdr.sdr.board_name == "bladerf1"
        assert sdr.sdr.fpga_configured
        print(f"Device: {sdr.sdr.board_name}, FW={sdr.sdr.fw_version}, FPGA={sdr.sdr.fpga_version}")


def test_receive_config():
    with BladeRFSdr() as sdr:
        sdr.config_rx(freq=2.4e9, sr=SR, gain=50)
        assert sdr.rx_ch.frequency == int(2.4e9)
        assert sdr.rx_ch.sample_rate == int(SR)
        assert sdr.rx_ch.gain == 50
        assert sdr._rx_enabled
        samples = Receiver(sdr).receive(1024)
        assert samples.shape == (1024,)
        assert np.isfinite(samples).all()
        print(f"RX OK — peak amplitude: {np.abs(samples).max():.4f}")


def test_transmit_config():
    with BladeRFSdr() as sdr:
        sdr.config_tx(freq=2.4e9, sr=SR, gain=-6)
        assert sdr.tx_ch.frequency == int(2.4e9)
        assert sdr.tx_ch.sample_rate == int(SR)
        assert sdr._tx_enabled
        tx = Transmitter(sdr)
        tone = tx.generate_tone(freq_hz=1e6, num_samples=1024, sample_rate=SR)
        tx.send(tone)
        print("TX OK — tone sent")


def test_sample_format():
    samples = np.array([1.0 + 1j, -1.0 - 1j], dtype=np.complex64)
    raw = Transmitter.prepare_tx(samples)
    recovered = Receiver.parse_samples(raw)
    assert recovered.shape[0] == 2
    assert np.allclose(recovered, samples, atol=1e-6)
    print("Sample format round-trip: OK")


if __name__ == "__main__":
    test_device_info()
    test_sample_format()
    test_receive_config()
    test_transmit_config()
    print("\nAll tests passed.")
