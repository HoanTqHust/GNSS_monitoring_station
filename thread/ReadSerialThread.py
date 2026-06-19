from __future__ import annotations

import logging
import queue as queue_module
from datetime import datetime, timezone
from typing import Any

import serial
from pyubx2 import NMEA_PROTOCOL, UBX_PROTOCOL, UBXReader

from config import config
from thread.RTKLIBStage import RTKLIBStage

LOGGER = logging.getLogger("thread.read_serial")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ReadSerial:
    @staticmethod
    def _should_emit_raw_frame(parsed_data: Any) -> bool:
        allowed_identities = config.RAW_UBX_ALLOWED_IDENTITIES
        if allowed_identities is None:
            return True
        identity = getattr(parsed_data, "identity", "UNKNOWN")
        return identity in allowed_identities

    @staticmethod
    def _is_synced_epoch(state1: dict[str, Any], state2: dict[str, Any]) -> bool:
        rawx1 = state1.get("rawx")
        rawx2 = state2.get("rawx")
        nav1 = state1.get("nav")
        nav2 = state2.get("nav")
        if rawx1 is None or rawx2 is None or nav1 is None or nav2 is None:
            return False
        return round(rawx1.rcvTow) == round(rawx2.rcvTow)

    @staticmethod
    def _next_event(seq_counter: int, event_type: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not event_type:
            raise ValueError("event_type must not be empty")
        if payload is None:
            raise ValueError("payload must not be None")
        next_seq = seq_counter + 1
        return next_seq, {
            "seq": next_seq,
            "event_type": event_type,
            "created_at_utc": _utc_now_iso(),
            "payload": payload,
        }

    @staticmethod
    def _enqueue_with_backpressure(ingress_queue, event: dict[str, Any], drop_stats: dict[str, int]) -> bool:
        try:
            ingress_queue.put_nowait(event)
            return True
        except queue_module.Full:
            drop_stats["ingress_dropped"] += 1
            LOGGER.warning(
                "ingress_queue_full_drop seq=%s event_type=%s dropped_total=%s",
                event.get("seq"),
                event.get("event_type"),
                drop_stats["ingress_dropped"],
            )
            return False

    @staticmethod
    def _consume_reader(
        reader: UBXReader,
        receiver_name: str,
        state: dict[str, Any],
    ) -> tuple[bytes, Any] | None:
        raw_data, parsed_data = reader.read()
        if raw_data is None or parsed_data is None:
            return None
        RTKLIBStage.normalize_receiver_state(parsed_data, state)
        return raw_data, parsed_data

    @staticmethod
    def read_serial(ingress_queue) -> None:
        state1: dict[str, Any] = {"rawx": None, "nav": None, "skyplot": "", "spectrum": ""}
        state2: dict[str, Any] = {"rawx": None, "nav": None, "skyplot": "", "spectrum": ""}
        seq_counter = 0
        drop_stats = {"ingress_dropped": 0, "raw_filtered": 0}

        with serial.Serial(config.PORT1, baudrate=115200, timeout=1) as ser1, serial.Serial(
            config.PORT2, baudrate=115200, timeout=1
        ) as ser2:
            LOGGER.info(
                "serial_ingest_started port1=%s port2=%s ingress_maxsize=%s",
                config.PORT1,
                config.PORT2,
                config.RAM_INGRESS_QUEUE_SIZE,
            )
            LOGGER.info(
                "raw_ubx_filter_started allowed_identities=%s",
                "*" if config.RAW_UBX_ALLOWED_IDENTITIES is None else ",".join(sorted(config.RAW_UBX_ALLOWED_IDENTITIES)),
            )
            reader1 = UBXReader(ser1, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)
            reader2 = UBXReader(ser2, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)

            while True:
                try:
                    read1 = ReadSerial._consume_reader(reader1, "rx1", state1)
                    if read1 is not None:
                        raw_data_1, parsed_data_1 = read1
                        if ReadSerial._should_emit_raw_frame(parsed_data_1):
                            frame_payload_1 = RTKLIBStage.normalize_frame("rx1", raw_data_1, parsed_data_1)
                            seq_counter, event_1 = ReadSerial._next_event(seq_counter, "ubx_frame", frame_payload_1)
                            ReadSerial._enqueue_with_backpressure(ingress_queue, event_1, drop_stats)
                        else:
                            drop_stats["raw_filtered"] += 1

                    read2 = ReadSerial._consume_reader(reader2, "rx2", state2)
                    if read2 is not None:
                        raw_data_2, parsed_data_2 = read2
                        if ReadSerial._should_emit_raw_frame(parsed_data_2):
                            frame_payload_2 = RTKLIBStage.normalize_frame("rx2", raw_data_2, parsed_data_2)
                            seq_counter, event_2 = ReadSerial._next_event(seq_counter, "ubx_frame", frame_payload_2)
                            ReadSerial._enqueue_with_backpressure(ingress_queue, event_2, drop_stats)
                        else:
                            drop_stats["raw_filtered"] += 1

                    if ReadSerial._is_synced_epoch(state1, state2):
                        epoch_payload = RTKLIBStage.normalize_epoch_pair(state1, state2)
                        seq_counter, epoch_event = ReadSerial._next_event(
                            seq_counter,
                            "epoch_pair",
                            epoch_payload,
                        )
                        ReadSerial._enqueue_with_backpressure(ingress_queue, epoch_event, drop_stats)
                        LOGGER.debug(
                            "epoch_pair_enqueued seq=%s tow_s=%.3f",
                            epoch_event["seq"],
                            float(epoch_payload["tow_s"]),
                        )
                        state1["rawx"] = None
                        state1["nav"] = None
                        state2["rawx"] = None
                        state2["nav"] = None
                except Exception:
                    LOGGER.exception("serial_ingest_error")
