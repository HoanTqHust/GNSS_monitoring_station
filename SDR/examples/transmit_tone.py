#!/usr/bin/env python3
"""
Transmit a tone on bladeRF.
Usage: python examples/transmit_tone.py [freq_hz] [tone_freq_hz] [num_samples]
"""
import sys
import time

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Transmitter


def main():
    freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4e9
    tone = float(sys.argv[2]) if len(sys.argv) > 2 else 1e6
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10 * 1024
    sr = 10e6

    samples = Transmitter.generate_tone(freq_hz=tone, num_samples=n, sample_rate=sr)
    samples *= 0.5  # amplitude scale

    with BladeRFSdr() as sdr:
        sdr.config_tx(freq=freq, sr=sr, gain=-6)
        tx = Transmitter(sdr)
        print(f"Transmitting {n} samples at {freq/1e6:.1f} MHz, tone={tone/1e6:.1f} MHz...")
        tx.send(samples)
        time.sleep(0.1)
        print("Done.")


if __name__ == "__main__":
    main()
