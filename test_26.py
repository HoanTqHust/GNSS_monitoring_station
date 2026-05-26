#!/usr/bin/env python3
"""
test_26.py -- Capture raw UBX data from 2 u-blox receivers for debug.

Reads continuously for ~5 minutes, saves all raw UBX frames.
- .ubx file per receiver (sequential raw UBX frames, compatible with u-center/RTKLIB)
- .json summary with parsed metadata

Uses pyubx2 UBXReader for proper protocol parsing (UBX + RTCM3 + NMEA mixed stream).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial
from pyubx2 import NMEA_PROTOCOL, RTCM3_PROTOCOL, UBX_PROTOCOL, UBXReader

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("test_26")

CAPTURE_DURATION_SEC = 300


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ReceiverCapture(threading.Thread):
    """Thread that reads UBX frames from one serial port and writes to .ubx file."""

    def __init__(self, port_path: str, label: str, end_time: float, ubx_path: Path):
        super().__init__(daemon=True)
        self._port = port_path
        self._label = label
        self._end_time = end_time
        self._ubx_path = ubx_path
        self._frames: list[dict] = []

    def run(self) -> None:
        LOGGER.info("[%s] capture started: port=%s -> %s", self._label, self._port, self._ubx_path)

        try:
            with serial.Serial(self._port, baudrate=115200, timeout=1) as ser:
                reader = UBXReader(
                    ser,
                    protfilter=UBX_PROTOCOL | RTCM3_PROTOCOL | NMEA_PROTOCOL,
                    validate=0,
                )
                with self._ubx_path.open("wb") as ubx_file:
                    count = 0
                    while time.time() < self._end_time:
                        raw, parsed = reader.read()
                        if raw is None or parsed is None:
                            # No data available right now; short sleep to avoid CPU spin
                            time.sleep(0.01)
                            continue

                        # Write every raw UBX frame to .ubx file
                        if raw[:2] == b"\xb5\x62":
                            ubx_file.write(raw)
                            count += 1
                        else:
                            # RTCM3 or NMEA - don't write to .ubx, but count
                            pass

                        # Log progress every 50 UBX frames
                        if count % 50 == 0 and raw[:2] == b"\xb5\x62":
                            identity = getattr(parsed, "identity", "UNKNOWN")
                            tow = getattr(parsed, "rcvTow", None)
                            LOGGER.info(
                                "[%s] %d ubx frames written  identity=%s  tow=%s",
                                self._label,
                                count,
                                identity,
                                tow,
                            )

                    LOGGER.info(
                        "[%s] capture done: %d frames written to %s",
                        self._label,
                        count,
                        self._ubx_path,
                    )
                    self._frame_count = count
        except serial.SerialException as e:
            LOGGER.error("[%s] serial error: %s", self._label, e)
            self._frame_count = 0

    @property
    def frames(self) -> list[dict]:
        return self._frames

    @property
    def frame_count(self) -> int:
        return getattr(self, "_frame_count", 0)


def main() -> None:
    end_time = time.time() + CAPTURE_DURATION_SEC

    output_dir = PROJECT_ROOT / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    ubx1 = output_dir / "test_26_rx1.ubx"
    ubx2 = output_dir / "test_26_rx2.ubx"
    json_out = output_dir / "test_26_raw.json"

    LOGGER.info(
        "Starting: PORT1=%s PORT2=%s  window=%ds",
        config.PORT1,
        config.PORT2,
        CAPTURE_DURATION_SEC,
    )

    rx1_cap = ReceiverCapture(config.PORT1, "rx1", end_time, ubx1)
    rx2_cap = ReceiverCapture(config.PORT2, "rx2", end_time, ubx2)

    rx1_cap.start()
    rx2_cap.start()

    LOGGER.info("Capture threads running... (ctrl+c to stop early)")

    try:
        rx1_cap.join()
        rx2_cap.join()
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")

    rx1_frames = rx1_cap.frames
    rx2_frames = rx2_cap.frames

    results = {
        "captured_at_utc": _iso_now(),
        "capture_duration_sec": CAPTURE_DURATION_SEC,
        "port1": config.PORT1,
        "port2": config.PORT2,
        "rx1_count": rx1_cap.frame_count,
        "rx2_count": rx2_cap.frame_count,
        "rx1": rx1_frames,
        "rx2": rx2_frames,
    }

    with json_out.open("w") as f:
        json.dump(results, f, indent=2)

    LOGGER.info("JSON summary: %s", json_out)
    print("\n=== Capture Summary ===")
    print(f"  rx1: {rx1_cap.frame_count} frames  -> {ubx1}")
    print(f"  rx2: {rx2_cap.frame_count} frames  -> {ubx2}")
    print(f"  JSON: {json_out}")


if __name__ == "__main__":
    main()
