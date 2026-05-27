#!/usr/bin/env python3
"""
Receive samples from bladeRF and plot PSD using numpy+maptlotlib.
Usage: python examples/receive_loop.py [freq_hz] [sample_rate] [num_samples]
"""
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Receiver


def psd(samples, fs):
    win = np.hanning(len(samples))
    s = samples * win
    fft = np.fft.fftshift(np.fft.fft(s))
    freq = np.fft.fftfreq(len(s), d=1 / fs)
    freq = np.fft.fftshift(freq)
    psd = 20 * np.log10(np.abs(fft) / np.abs(s).max() + 1e-12)
    return freq, psd


def main():
    freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4e9
    sr = float(sys.argv[2]) if len(sys.argv) > 2 else 10e6
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 1024 * 1024

    with BladeRFSdr() as sdr:
        sdr.config_rx(freq=freq, sr=sr, gain=50)
        rx = Receiver(sdr)
        print(f"Receiving {n} samples at {freq/1e6:.1f} MHz, SR={sr/1e6:.1f} Msps...")
        samples = rx.receive(n)
        print(f"Done. Peak amplitude: {np.abs(samples).max():.3f}")

    freq_axis, p = psd(samples, sr)
    plt.figure(figsize=(10, 5))
    plt.plot(freq_axis / 1e6, p)
    plt.xlabel("Frequency (MHz)")
    plt.ylabel("PSD (dB)")
    plt.title(f"RX @ {freq/1e6:.1f} MHz")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
