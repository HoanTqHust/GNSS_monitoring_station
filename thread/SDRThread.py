"""
SDR Thread - BladeRF data capture and streaming via SocketIO
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
from flask_socketio import SocketIO

import sys
sys.path.insert(0, "/home/firefly/double_difference_cp/SDR")
from src import BladeRFSdr, Receiver

from config import config

LOGGER = logging.getLogger("thread.sdr_thread")


class SDRThread:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.running = False
        self.thread = None
        self.sdr = None
        self.rx = None

    @staticmethod
    def get_instance(socketio: SocketIO) -> "SDRThread":
        with SDRThread._lock:
            if SDRThread._instance is None:
                SDRThread._instance = SDRThread(socketio)
            return SDRThread._instance

    def start(self) -> None:
        """Start the SDR capture thread"""
        if self.running:
            LOGGER.warning("SDR thread already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True, name="sdr-capture")
        self.thread.start()
        LOGGER.info("SDR thread started")

    def stop(self) -> None:
        """Stop the SDR capture thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        LOGGER.info("SDR thread stopped")

    def _capture_loop(self) -> None:
        """Main capture loop"""
        if not config.SDR_ENABLED:
            LOGGER.info("SDR disabled in config")
            return

        LOGGER.info(f"Starting SDR capture: freq={config.SDR_FREQ/1e6:.2f}MHz sr={config.SDR_SAMPLE_RATE/1e6:.1f}MHz")

        try:
            self.sdr = BladeRFSdr(device_string=config.SDR_DEVICE)
            self.sdr.config_rx(
                freq=config.SDR_FREQ,
                sr=config.SDR_SAMPLE_RATE,
                gain=config.SDR_GAIN,
                bw=config.SDR_BANDWIDTH
            )
            self.rx = Receiver(self.sdr)
            LOGGER.info(f"BladeRF initialized: {self.sdr.sdr.board_name}")

            while self.running:
                try:
                    samples = self.rx.receive(config.SDR_NUM_SAMPLES)
                    samples = samples - samples.mean()  # DC removal

                    # Compute stats
                    amplitude = np.abs(samples)
                    peak = float(amplitude.max())
                    mean = float(amplitude.mean())

                    # Prepare IQ data for constellation (downsample for display)
                    display_samples = samples[::4]  # downsample 4x
                    iq_data = np.column_stack((display_samples.real, display_samples.imag)).flatten().tolist()

                    # Emit via SocketIO
                    self.socketio.emit("sdr_data", {
                        "amp": amplitude.tolist()[:500],  # limit for browser
                        "peak": peak,
                        "mean": mean,
                        "iq": iq_data,  # already limited at column_stack
                        "timestamp": time.time(),
                    })

                except Exception as e:
                    LOGGER.error(f"Capture error: {e}")
                    time.sleep(0.1)

        except Exception as e:
            LOGGER.error(f"SDR init error: {e}")
        finally:
            if self.sdr:
                self.sdr.close()
                self.sdr = None

    @property
    def is_running(self) -> bool:
        return self.running and self.thread is not None and self.thread.is_alive()