from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


UBX_SYNC = b"\xb5\x62"
UBX_PROTOCOL_MASK = 0x01
NMEA_PROTOCOL_MASK = 0x02
RTCM3_PROTOCOL_MASK = 0x04


@dataclass(frozen=True)
class UbloxMessage:
    identity: str
    msg_class: int
    msg_id: int


@dataclass(frozen=True)
class UbloxCommand:
    description: str
    frame: bytes


DASHBOARD_MESSAGES: Tuple[UbloxMessage, ...] = (
    UbloxMessage("RXM-RAWX", 0x02, 0x15),
    UbloxMessage("NAV-PVT", 0x01, 0x07),
    UbloxMessage("NAV-SAT", 0x01, 0x35),
    UbloxMessage("MON-SPAN", 0x0A, 0x31),
)


NMEA_MESSAGES_TO_DISABLE: Tuple[UbloxMessage, ...] = tuple(
    UbloxMessage(f"NMEA-F0-{msg_id:02X}", 0xF0, msg_id)
    for msg_id in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0D, 0x0F, 0x10)
) + tuple(
    UbloxMessage(f"NMEA-F1-{msg_id:02X}", 0xF1, msg_id)
    for msg_id in (0x00, 0x01, 0x03, 0x04, 0x05, 0x06)
)


UBX_MESSAGES_TO_DISABLE: Tuple[UbloxMessage, ...] = (
    UbloxMessage("NAV-POSECEF", 0x01, 0x01),
    UbloxMessage("NAV-POSLLH", 0x01, 0x02),
    UbloxMessage("NAV-STATUS", 0x01, 0x03),
    UbloxMessage("NAV-DOP", 0x01, 0x04),
    UbloxMessage("NAV-ODO", 0x01, 0x09),
    UbloxMessage("NAV-VELECEF", 0x01, 0x11),
    UbloxMessage("NAV-VELNED", 0x01, 0x12),
    UbloxMessage("NAV-HPPOSECEF", 0x01, 0x13),
    UbloxMessage("NAV-HPPOSLLH", 0x01, 0x14),
    UbloxMessage("NAV-TIMEGPS", 0x01, 0x20),
    UbloxMessage("NAV-TIMEUTC", 0x01, 0x21),
    UbloxMessage("NAV-CLOCK", 0x01, 0x22),
    UbloxMessage("NAV-TIMEGLO", 0x01, 0x23),
    UbloxMessage("NAV-TIMEBDS", 0x01, 0x24),
    UbloxMessage("NAV-TIMEGAL", 0x01, 0x25),
    UbloxMessage("NAV-TIMELS", 0x01, 0x26),
    UbloxMessage("NAV-TIMEQZSS", 0x01, 0x27),
    UbloxMessage("NAV-SBAS", 0x01, 0x32),
    UbloxMessage("NAV-ORB", 0x01, 0x34),
    UbloxMessage("NAV-COV", 0x01, 0x36),
    UbloxMessage("NAV-GEOFENCE", 0x01, 0x39),
    UbloxMessage("NAV-SVIN", 0x01, 0x3B),
    UbloxMessage("NAV-RELPOSNED", 0x01, 0x3C),
    UbloxMessage("NAV-SLAS", 0x01, 0x42),
    UbloxMessage("NAV-SIG", 0x01, 0x43),
    UbloxMessage("NAV-EOE", 0x01, 0x61),
    UbloxMessage("NAV-PL", 0x01, 0x62),
    UbloxMessage("RXM-SFRBX", 0x02, 0x13),
    UbloxMessage("RXM-MEASX", 0x02, 0x14),
    UbloxMessage("MON-IO", 0x0A, 0x02),
    UbloxMessage("MON-MSGPP", 0x0A, 0x06),
    UbloxMessage("MON-RXBUF", 0x0A, 0x07),
    UbloxMessage("MON-TXBUF", 0x0A, 0x08),
    UbloxMessage("MON-HW", 0x0A, 0x09),
    UbloxMessage("MON-HW2", 0x0A, 0x0B),
    UbloxMessage("MON-COMMS", 0x0A, 0x36),
    UbloxMessage("MON-HW3", 0x0A, 0x37),
    UbloxMessage("MON-RF", 0x0A, 0x38),
    UbloxMessage("MON-SYS", 0x0A, 0x39),
    UbloxMessage("SEC-SIG", 0x27, 0x09),
    UbloxMessage("SEC-SIGLOG", 0x27, 0x10),
    UbloxMessage("TIM-TP", 0x0D, 0x01),
)


def ubx_frame(msg_class: int, msg_id: int, payload: bytes) -> bytes:
    _validate_byte("msg_class", msg_class)
    _validate_byte("msg_id", msg_id)
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) > 0xFFFF:
        raise ValueError("payload is too large for UBX frame")

    header_without_sync = bytes([msg_class, msg_id]) + len(payload).to_bytes(2, "little")
    ck_a, ck_b = ubx_checksum(header_without_sync + payload)
    return UBX_SYNC + header_without_sync + payload + bytes([ck_a, ck_b])


def ubx_checksum(data: bytes) -> Tuple[int, int]:
    ck_a = 0
    ck_b = 0
    for value in data:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def cfg_msg_all_ports(message: UbloxMessage, rate: int) -> bytes:
    _validate_byte("rate", rate)
    payload = bytes(
        [
            message.msg_class,
            message.msg_id,
            rate,
            rate,
            rate,
            rate,
            rate,
            0x00,
        ]
    )
    return ubx_frame(0x06, 0x01, payload)


def cfg_prt_usb_ubx_only() -> bytes:
    payload = (
        bytes([0x03, 0x00, 0x00, 0x00])
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + UBX_PROTOCOL_MASK.to_bytes(2, "little")
        + UBX_PROTOCOL_MASK.to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
    )
    return ubx_frame(0x06, 0x00, payload)


def cfg_cfg_save_current() -> bytes:
    clear_mask = (0).to_bytes(4, "little")
    save_mask = (0xFFFF).to_bytes(4, "little")
    load_mask = (0).to_bytes(4, "little")
    return ubx_frame(0x06, 0x09, clear_mask + save_mask + load_mask)


def build_dashboard_config_commands(save: bool = True) -> List[UbloxCommand]:
    target_keys = {(message.msg_class, message.msg_id) for message in DASHBOARD_MESSAGES}
    commands: List[UbloxCommand] = [UbloxCommand("Set USB input/output protocol to UBX only", cfg_prt_usb_ubx_only())]

    for message in _unique_messages(NMEA_MESSAGES_TO_DISABLE + UBX_MESSAGES_TO_DISABLE):
        if (message.msg_class, message.msg_id) in target_keys:
            continue
        commands.append(UbloxCommand(f"Disable {message.identity}", cfg_msg_all_ports(message, rate=0)))

    for message in DASHBOARD_MESSAGES:
        commands.append(UbloxCommand(f"Enable {message.identity}", cfg_msg_all_ports(message, rate=1)))

    if save:
        commands.append(UbloxCommand("Save current configuration to non-volatile memory", cfg_cfg_save_current()))

    return commands


def dashboard_identity_names() -> Tuple[str, ...]:
    return tuple(message.identity for message in DASHBOARD_MESSAGES)


def _unique_messages(messages: Iterable[UbloxMessage]) -> Tuple[UbloxMessage, ...]:
    seen = set()
    unique = []
    for message in messages:
        key = (message.msg_class, message.msg_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(message)
    return tuple(unique)


def _validate_byte(name: str, value: int) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be between 0 and 255")
