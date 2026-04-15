from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import serial
from pyubx2 import NMEA_PROTOCOL, UBX_PROTOCOL, UBXReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from models.RAWXData import RAWXData
from realtime.pipeline import RealtimeSpoofingPipeline
from realtime.types import RealtimeEpochPair

LOGGER = logging.getLogger("realtime.live_runner")


@dataclass
class ReceiverState:
    rawx: RAWXData | None = None
    nav: object | None = None


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def read_live_epoch_pairs(
    port1: str,
    port2: str,
    baudrate: int,
    tow_tolerance_s: float,
):
    state1 = ReceiverState()
    state2 = ReceiverState()

    with serial.Serial(port1, baudrate=baudrate, timeout=1) as ser1, serial.Serial(
        port2, baudrate=baudrate, timeout=1
    ) as ser2:
        LOGGER.info("opened_serial_ports port1=%s port2=%s baudrate=%s", port1, port2, baudrate)
        reader1 = UBXReader(ser1, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)
        reader2 = UBXReader(ser2, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)

        while True:
            _consume_reader(reader1, state1, "rx1")
            _consume_reader(reader2, state2, "rx2")

            epoch_pair = _build_epoch_pair(state1, state2, tow_tolerance_s)
            if epoch_pair is None:
                continue

            yield epoch_pair
            state1.rawx = None
            state1.nav = None
            state2.rawx = None
            state2.nav = None


def _consume_reader(reader: UBXReader, state: ReceiverState, receiver_name: str) -> None:
    raw_data, parsed_data = reader.read()
    if raw_data is None or parsed_data is None:
        return

    identity = parsed_data.identity
    if identity == "RXM-RAWX":
        state.rawx = RAWXData(parsed_data)
        LOGGER.debug("received_rawx receiver=%s tow=%.3f", receiver_name, state.rawx.rcvTow)
    elif identity == "NAV-PVT":
        state.nav = parsed_data
        LOGGER.debug("received_nav_pvt receiver=%s", receiver_name)


def _build_epoch_pair(
    state1: ReceiverState,
    state2: ReceiverState,
    tow_tolerance_s: float,
) -> RealtimeEpochPair | None:
    if state1.rawx is None or state2.rawx is None:
        return None

    tow1 = float(state1.rawx.rcvTow)
    tow2 = float(state2.rawx.rcvTow)
    tow_diff = abs(tow1 - tow2)
    if tow_diff > tow_tolerance_s:
        LOGGER.debug(
            "skip_unsynced_epoch tow1=%.3f tow2=%.3f tow_diff=%.6f tolerance=%.6f",
            tow1,
            tow2,
            tow_diff,
            tow_tolerance_s,
        )
        if tow1 < tow2:
            state1.rawx = None
            state1.nav = None
        else:
            state2.rawx = None
            state2.nav = None
        return None

    epoch_pair = RealtimeEpochPair(
        tow_s=min(tow1, tow2),
        rawx_1=state1.rawx,
        nav_1=state1.nav,
        rawx_2=state2.rawx,
        nav_2=state2.nav,
    )
    LOGGER.info("synced_epoch tow=%.3f tow_diff=%.6f", epoch_pair.tow_s, tow_diff)
    return epoch_pair


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone live runner for realtime spoofing detection."
    )
    parser.add_argument("--port1", default=config.PORT1, help="Serial port for receiver 1.")
    parser.add_argument("--port2", default=config.PORT2, help="Serial port for receiver 2.")
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate for both receivers.",
    )
    parser.add_argument(
        "--tow-tolerance",
        type=float,
        default=0.05,
        help="Maximum allowed TOW difference in seconds for pairing epochs.",
    )
    parser.add_argument(
        "--output-root",
        default="output_rt",
        help="Directory where detector JSONL outputs are written.",
    )
    parser.add_argument(
        "--max-epochs",
        type=int,
        default=None,
        help="Optional limit for processed live epochs, useful for smoke tests.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(debug=args.debug)
    pipeline = RealtimeSpoofingPipeline(output_root=args.output_root)

    processed_epochs = 0
    LOGGER.info(
        "starting_live_runner port1=%s port2=%s output_root=%s",
        args.port1,
        args.port2,
        args.output_root,
    )
    for epoch_pair in read_live_epoch_pairs(
        port1=args.port1,
        port2=args.port2,
        baudrate=args.baudrate,
        tow_tolerance_s=args.tow_tolerance,
    ):
        results = pipeline.process_epoch(epoch_pair)
        processed_epochs += 1
        LOGGER.info(
            "processed_epoch tow=%.3f detector_results=%s processed_epochs=%s",
            epoch_pair.tow_s,
            len(results),
            processed_epochs,
        )
        if args.max_epochs is not None and processed_epochs >= args.max_epochs:
            LOGGER.info("max_epochs_reached processed_epochs=%s", processed_epochs)
            break


if __name__ == "__main__":
    main()
