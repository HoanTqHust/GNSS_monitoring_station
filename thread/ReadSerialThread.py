from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

import serial
from pyubx2 import NMEA_PROTOCOL, UBX_PROTOCOL, UBXReader

from config import config
from models.RAWXData import RAWXData
from thread.DurableRawQueue import DurableRawQueue

LOGGER = logging.getLogger("thread.read_serial")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ReadSerial:
    @staticmethod
    def _build_raw_frame_payload(receiver_name: str, raw_data: bytes, parsed_data: Any) -> dict[str, Any]:
        identity = getattr(parsed_data, "identity", "UNKNOWN")
        tow_value = getattr(parsed_data, "rcvTow", None)
        tow_s = float(tow_value) if tow_value is not None else None
        return {
            "received_at_utc": _utc_now_iso(),
            "receiver": receiver_name,
            "identity": identity,
            "tow_s": tow_s,
            "raw_len": len(raw_data),
            "raw_base64": base64.b64encode(raw_data).decode("ascii"),
        }

    @staticmethod
    def _consume_reader(
        reader: UBXReader,
        receiver_name: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]] | None:
        raw_data, parsed_data = reader.read()
        if raw_data is None or parsed_data is None:
            return None

        identity = getattr(parsed_data, "identity", "UNKNOWN")
        if identity == "NAV-SAT":
            state["skyplot"] = parsed_data
        elif identity == "MON-SPAN":
            state["spectrum"] = parsed_data
        elif identity == "RXM-RAWX":
            state["rawx"] = RAWXData(parsed_data)
        elif identity == "NAV-PVT":
            state["nav"] = parsed_data

        return ("ubx_frame", ReadSerial._build_raw_frame_payload(receiver_name, raw_data, parsed_data))

    @staticmethod
    def _is_synced_epoch(state1: dict[str, Any], state2: dict[str, Any]) -> bool:
        rawx1 = state1["rawx"]
        rawx2 = state2["rawx"]
        nav1 = state1["nav"]
        nav2 = state2["nav"]
        if rawx1 is None or rawx2 is None or nav1 is None or nav2 is None:
            return False
        return round(rawx1.rcvTow) == round(rawx2.rcvTow)

    @staticmethod
    def _build_epoch_payload(state1: dict[str, Any], state2: dict[str, Any]) -> dict[str, Any]:
        rawx1 = state1["rawx"]
        rawx2 = state2["rawx"]
        if rawx1 is None or rawx2 is None:
            raise ValueError("rawx state must not be None when building epoch payload")
        return {
            "received_at_utc": _utc_now_iso(),
            "tow_s": min(float(rawx1.rcvTow), float(rawx2.rcvTow)),
            "rawx_1": state1["rawx"],
            "nav_1": state1["nav"],
            "rawx_2": state2["rawx"],
            "nav_2": state2["nav"],
            "skyplot_data_1": state1["skyplot"],
            "skyplot_data_2": state2["skyplot"],
            "spectrum_data_1": state1["spectrum"],
            "spectrum_data_2": state2["spectrum"],
        }

    @staticmethod
    def read_serial(raw_queue_db_path: str | None = None) -> None:
        queue_path = raw_queue_db_path or config.RAW_QUEUE_DB_PATH
        durable_queue = DurableRawQueue(queue_path)

        state1: dict[str, Any] = {"rawx": None, "nav": None, "skyplot": "", "spectrum": ""}
        state2: dict[str, Any] = {"rawx": None, "nav": None, "skyplot": "", "spectrum": ""}

        with serial.Serial(config.PORT1, baudrate=115200, timeout=1) as ser1, serial.Serial(
            config.PORT2, baudrate=115200, timeout=1
        ) as ser2:
            LOGGER.info(
                "serial_ingest_started port1=%s port2=%s queue_db_path=%s",
                config.PORT1,
                config.PORT2,
                queue_path,
            )
            reader1 = UBXReader(ser1, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)
            reader2 = UBXReader(ser2, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)

            while True:
                events_to_enqueue: list[tuple[str, dict[str, Any]]] = []
                try:
                    event1 = ReadSerial._consume_reader(reader1, "rx1", state1)
                    if event1 is not None:
                        events_to_enqueue.append(event1)

                    event2 = ReadSerial._consume_reader(reader2, "rx2", state2)
                    if event2 is not None:
                        events_to_enqueue.append(event2)

                    if ReadSerial._is_synced_epoch(state1, state2):
                        epoch_payload = ReadSerial._build_epoch_payload(state1, state2)
                        events_to_enqueue.append(("epoch_pair", epoch_payload))
                        LOGGER.debug(
                            "synced_epoch_enqueued tow_s=%.3f rx1_tow=%.3f rx2_tow=%.3f",
                            epoch_payload["tow_s"],
                            float(state1["rawx"].rcvTow),
                            float(state2["rawx"].rcvTow),
                        )
                        state1["rawx"] = None
                        state1["nav"] = None
                        state2["rawx"] = None
                        state2["nav"] = None

                    if events_to_enqueue:
                        last_seq = durable_queue.enqueue_many(events_to_enqueue)
                        LOGGER.debug(
                            "raw_events_enqueued count=%s last_seq=%s",
                            len(events_to_enqueue),
                            last_seq,
                        )
                except Exception:
                    LOGGER.exception("serial_ingest_error")
