#!/usr/bin/env python3
"""
Quick spectrogram test - save one BMP without Qt UI
"""
import os
import sys
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

sys.path.insert(0, "/home/firefly/double_difference_cp")
sys.path.insert(0, "/home/firefly/double_difference_cp/SDR")
from SDR.src import BladeRFSdr, Receiver
from config import config

SAMPLE_RATE = 60e6
CENTER_FREQ = 1575.42e6
GAIN = 40  # try higher gain

WINDOW_LEN = 512
NOVERLAP = 384
NFFT = 512
FMIN_MHZ = -15.0
FMAX_MHZ = 15.0
DYN_RANGE_DB = 55
IMG_W = 640
IMG_H = 480
NUM_BUFFERS = 8

_COLORS = [
    (0.00, "#000000"),
    (0.20, "#0d0d3a"),
    (0.38, "#1a1a8c"),
    (0.55, "#0055ff"),
    (0.68, "#00ccff"),
    (0.80, "#00ffcc"),
    (0.90, "#aaff00"),
    (0.97, "#ffff00"),
    (1.00, "#ffffff"),
]
_cmap = LinearSegmentedColormap.from_list("sdr_waterfall", [(v, c) for v, c in _COLORS])
_LUT = (_cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)


def compute_spectrogram(x):
    x = x - x.mean()
    hop = WINDOW_LEN - NOVERLAP
    win = np.hanning(WINDOW_LEN).astype(np.float32)
    if len(x) < WINDOW_LEN:
        return np.zeros((NFFT, 1), dtype=np.float32)
    n_frm = 1 + (len(x) - WINDOW_LEN) // hop
    SY = np.empty((NFFT, n_frm), dtype=np.complex64)
    for k in range(n_frm):
        s = k * hop
        SY[:, k] = np.fft.fft(x[s:s + WINDOW_LEN] * win, n=NFFT)
    SY = np.fft.fftshift(SY, axes=0)
    FY = np.fft.fftshift(np.fft.fftfreq(NFFT, d=1.0 / SAMPLE_RATE)) / 1e6
    mask = (FY >= FMIN_MHZ) & (FY <= FMAX_MHZ)
    power_db = 10 * np.log10(np.abs(SY[mask]) ** 2 + 1e-12)
    return power_db


def render_bmp(power_db):
    vmax = np.percentile(power_db, 99.5)
    vmin = vmax - DYN_RANGE_DB
    denom = max(vmax - vmin, 1e-6)
    idx = np.clip((power_db - vmin) / denom, 0.0, 1.0)
    idx = (idx * 255).astype(np.uint8)[::-1, :]
    rgb = _LUT[idx]
    return Image.fromarray(rgb, mode="RGB").resize((IMG_W, IMG_H), Image.BILINEAR)


print(f"Starting bladeRF with gain={GAIN}...")
sdr = BladeRFSdr(device_string=config.SDR_DEVICE)
sdr.config_rx(freq=CENTER_FREQ, sr=SAMPLE_RATE, gain=GAIN, bw=SAMPLE_RATE/2)
rx = Receiver(sdr)

print("Collecting samples...")
chunks = []
for i in range(NUM_BUFFERS):
    samples = rx.receive(8192)
    iq = samples.astype(np.complex64)
    chunks.append(iq)
    print(f"  Buffer {i+1}/{NUM_BUFFERS}: {len(iq)} samples, mean={np.abs(iq).mean():.4f}")

frame = np.concatenate(chunks)
print(f"Total frame: {len(frame)} samples")

print("Computing spectrogram...")
power_db = compute_spectrogram(frame)
print(f"Spectrogram shape: {power_db.shape}, min={power_db.min():.2f}, max={power_db.max():.2f}, mean={power_db.mean():.2f}")

print("Rendering BMP...")
img = render_bmp(power_db)

output_path = "/home/firefly/double_difference_cp/BKDATASET/test_single.bmp"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
img.save(output_path)
print(f"Saved to {output_path}")

arr = np.array(img)
print(f"Image stats: mean={arr.mean():.1f}, min={arr.min()}, max={arr.max()}")
print(f"R/G/B means: {arr[:,:,0].mean():.1f} / {arr[:,:,1].mean():.1f} / {arr[:,:,2].mean():.1f}")

sdr.close()
print("Done!")