"""
SDR Thread - BladeRF data capture with spectrogram BMP pipeline
Follows test.py pattern: reader_process -> queue -> plotter_process -> BMP
"""

from __future__ import annotations

import logging
import os
import time
import signal
import threading
import multiprocessing as mp
from datetime import datetime
from typing import Any

import numpy as np
from flask_socketio import SocketIO
from matplotlib.colors import LinearSegmentedColormap
import matplotlib
matplotlib.use("Agg")

import sys
sys.path.insert(0, "/home/firefly/double_difference_cp/SDR")
from src import BladeRFSdr, Receiver

from config import config

LOGGER = logging.getLogger("thread.sdr_thread")

# ══════════════════════════════════════════════
# CONFIG (mirror of test.py)
# ══════════════════════════════════════════════
SAMPLE_RATE  = 60e6
CENTER_FREQ  = 1575.42e6
GAIN         = 20

BUFFER_SIZE  = 8192
NUM_BUFFERS  = 8

WINDOW_LEN   = 512
NOVERLAP     = 384
NFFT         = 512
FMIN_MHZ     = -15.0
FMAX_MHZ     =  15.0
DYN_RANGE_DB = 55

OUTPUT_DIR   = "./BKDATASET/"
IMG_W        = 640
IMG_H        = 480

THROTTLE_S    = 0.1
QUEUE_MAXSIZE = 32

GUI_REFRESH_MS = 500

# ══════════════════════════════════════════════
# COLORMAP
# ══════════════════════════════════════════════
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
_cmap = LinearSegmentedColormap.from_list(
    "sdr_waterfall", [(v, c) for v, c in _COLORS]
)
_LUT = (_cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)

# ══════════════════════════════════════════════
# HELPER — spectrogram
# ══════════════════════════════════════════════
def compute_spectrogram(x: np.ndarray) -> np.ndarray:
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


# ══════════════════════════════════════════════
# HELPER — render BMP
# ══════════════════════════════════════════════
def render_bmp(power_db: np.ndarray):
    from PIL import Image
    vmax = np.percentile(power_db, 99.5)
    vmin = vmax - DYN_RANGE_DB

    denom = max(vmax - vmin, 1e-6)
    idx = np.clip((power_db - vmin) / denom, 0.0, 1.0)
    idx = (idx * 255).astype(np.uint8)
    idx = idx[::-1, :]

    rgb = _LUT[idx]
    return Image.fromarray(rgb, mode="RGB").resize((IMG_W, IMG_H), Image.BILINEAR)


# ══════════════════════════════════════════════
# PROCESS A — reader
# ══════════════════════════════════════════════
def reader_process(queue: mp.Queue, stop_event: mp.Event):
    sys.path.insert(0, "/home/firefly/double_difference_cp/SDR")
    from src import BladeRFSdr, Receiver

    sdr = BladeRFSdr(device_string=config.SDR_DEVICE)
    sdr.config_rx(
        freq=CENTER_FREQ,
        sr=SAMPLE_RATE,
        gain=GAIN,
        bw=SAMPLE_RATE / 2
    )
    rx = Receiver(sdr)

    buf = bytearray(BUFFER_SIZE * 4)
    last_push_t = 0.0
    chunks = []

    print(f"[reader] started — push mỗi {THROTTLE_S*1000:.0f} ms")

    try:
        while not stop_event.is_set():
            raw_samples = rx.receive(BUFFER_SIZE)
            iq = raw_samples.astype(np.complex64)

            chunks.append(iq)
            if len(chunks) > NUM_BUFFERS:
                chunks.pop(0)

            now = time.monotonic()
            if now - last_push_t >= THROTTLE_S and len(chunks) == NUM_BUFFERS:
                frame = np.concatenate(chunks).astype(np.complex64)
                try:
                    queue.put_nowait(frame)
                except Exception:
                    pass
                last_push_t = now

    except Exception as e:
        print(f"[reader] error: {e}")
    finally:
        sdr.close()
        print("[reader] stopped")


# ══════════════════════════════════════════════
# PROCESS B — plotter
# ══════════════════════════════════════════════
def plotter_process(queue: mp.Queue, stop_event: mp.Event):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    frame_idx = 0
    t0 = time.time()
    cnt = 0

    print(f"[plotter] saving -> {OUTPUT_DIR}")

    while not stop_event.is_set():
        try:
            x = queue.get(timeout=2.0)
        except Exception:
            continue

        try:
            power_db = compute_spectrogram(x)
            img = render_bmp(power_db)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(OUTPUT_DIR, f"{ts}_{frame_idx:06d}.bmp")
            img.save(path, format="BMP")

            frame_idx += 1
            cnt += 1

            elapsed = time.time() - t0
            if elapsed >= 5.0:
                print(f"[plotter] {cnt/elapsed:.2f} fps | total: {frame_idx}")
                t0 = time.time()
                cnt = 0
        except Exception as e:
            print(f"[plotter] error: {e}")

    print(f"[plotter] stopped — total saved: {frame_idx}")


# ══════════════════════════════════════════════
# SDRThread
# ══════════════════════════════════════════════
class SDRThread:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.running = False
        self.processes = []
        self.queue = None
        self.stop_event = None

    @staticmethod
    def get_instance(socketio: SocketIO) -> "SDRThread":
        with SDRThread._lock:
            if SDRThread._instance is None:
                SDRThread._instance = SDRThread(socketio)
            return SDRThread._instance

    def start(self) -> None:
        """Start the SDR capture pipeline (reader + plotter processes)"""
        if self.running:
            LOGGER.warning("SDR thread already running")
            return

        self.running = True
        self.queue = mp.Queue(maxsize=QUEUE_MAXSIZE)
        self.stop_event = mp.Event()

        p_reader = mp.Process(
            target=reader_process,
            args=(self.queue, self.stop_event),
            daemon=True
        )
        p_plotter = mp.Process(
            target=plotter_process,
            args=(self.queue, self.stop_event),
            daemon=True
        )

        p_reader.start()
        p_plotter.start()

        self.processes = [p_reader, p_plotter]
        LOGGER.info("SDR pipeline started (reader + plotter)")

    def stop(self) -> None:
        """Stop the SDR capture pipeline"""
        if self.stop_event:
            self.stop_event.set()

        for p in self.processes:
            if p.is_alive():
                p.join(timeout=2.0)

        self.processes = []
        self.running = False
        LOGGER.info("SDR pipeline stopped")

    @property
    def is_running(self) -> bool:
        return self.running and any(p.is_alive() for p in self.processes)