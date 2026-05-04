from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

from models.RAWXData import RAWXData


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RTKLIBStage:
    """
    Logical RTKLIB stage adapter.

    This module normalizes parsed u-blox frames into event payloads that can be
    transported over RAM queues. It does not persist state.
    """

    @staticmethod
    def normalize_frame(receiver_name: str, raw_data: bytes, parsed_data: Any) -> dict[str, Any]:
        if not receiver_name:
            raise ValueError("receiver_name must not be empty")
        if raw_data is None:
            raise ValueError("raw_data must not be None")
        if parsed_data is None:
            raise ValueError("parsed_data must not be None")

        identity = getattr(parsed_data, "identity", "UNKNOWN")
        tow_value = getattr(parsed_data, "rcvTow", None)
        tow_s = float(tow_value) if tow_value is not None else None

        return {
            "stage": "rtklib",
            "received_at_utc": utc_now_iso(),
            "receiver": receiver_name,
            "identity": identity,
            "tow_s": tow_s,
            "raw_len": len(raw_data),
            "raw_base64": base64.b64encode(raw_data).decode("ascii"),
        }

    @staticmethod
    def normalize_receiver_state(parsed_data: Any, state: dict[str, Any]) -> None:
        if parsed_data is None:
            raise ValueError("parsed_data must not be None")
        if state is None:
            raise ValueError("state must not be None")

        identity = getattr(parsed_data, "identity", "UNKNOWN")
        if identity == "NAV-SAT":
            state["skyplot"] = parsed_data
        elif identity == "MON-SPAN":
            state["spectrum"] = parsed_data
        elif identity == "RXM-RAWX":
            state["rawx"] = RAWXData(parsed_data)
        elif identity == "NAV-PVT":
            state["nav"] = parsed_data

    @staticmethod
    def normalize_epoch_pair(state1: dict[str, Any], state2: dict[str, Any]) -> dict[str, Any]:
        rawx1 = state1.get("rawx")
        rawx2 = state2.get("rawx")
        if rawx1 is None or rawx2 is None:
            raise ValueError("rawx for both receivers is required")

        return {
            "stage": "rtklib",
            "received_at_utc": utc_now_iso(),
            "tow_s": min(float(rawx1.rcvTow), float(rawx2.rcvTow)),
            "rawx_1": state1.get("rawx"),
            "nav_1": state1.get("nav"),
            "rawx_2": state2.get("rawx"),
            "nav_2": state2.get("nav"),
            "skyplot_data_1": state1.get("skyplot"),
            "skyplot_data_2": state2.get("skyplot"),
            "spectrum_data_1": state1.get("spectrum"),
            "spectrum_data_2": state2.get("spectrum"),
        }
