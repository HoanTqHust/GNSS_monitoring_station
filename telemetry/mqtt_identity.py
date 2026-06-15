from __future__ import annotations

import os
import re
from typing import Optional


DEVICE_ID_PATTERN = re.compile(r"^device_[0-9A-Fa-f]{4,12}$")
TOPIC_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def normalize_mac_address(value: str) -> str:
    mac = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if len(mac) != 12:
        raise ValueError("MAC address must contain exactly 12 hexadecimal characters")
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", mac):
        raise ValueError("MAC address contains non-hexadecimal characters")
    if mac == "000000000000":
        raise ValueError("MAC address must not be all zeroes")
    return mac.lower()


def mac_to_device_id(mac_address: str, suffix_length: int = 4) -> str:
    if not (4 <= int(suffix_length) <= 12):
        raise ValueError("MQTT_DEVICE_MAC_SUFFIX_LENGTH must be in range 4..12")
    normalized = normalize_mac_address(mac_address)
    return f"device_{normalized[-int(suffix_length):]}"


def read_mac_from_interface(interface_name: str, sys_class_net: str = "/sys/class/net") -> Optional[str]:
    if not interface_name:
        return None
    address_path = os.path.join(sys_class_net, interface_name, "address")
    try:
        with open(address_path, "r", encoding="utf-8") as address_file:
            return normalize_mac_address(address_file.read().strip())
    except FileNotFoundError:
        return None
    except ValueError:
        return None


def is_candidate_network_interface(interface_name: str) -> bool:
    if not interface_name:
        return False
    ignored_prefixes = ("lo", "docker", "veth", "br-", "virbr", "tun", "tap")
    return not interface_name.startswith(ignored_prefixes)


def find_primary_mac_address(
    *,
    preferred_interface: str = "",
    sys_class_net: str = "/sys/class/net",
) -> str:
    preferred_mac = read_mac_from_interface(preferred_interface, sys_class_net)
    if preferred_mac:
        return preferred_mac

    try:
        interface_names = sorted(os.listdir(sys_class_net))
    except FileNotFoundError as exc:
        raise ValueError(f"network interface path not found: {sys_class_net}") from exc

    for interface_name in interface_names:
        if not is_candidate_network_interface(interface_name):
            continue
        mac_address = read_mac_from_interface(interface_name, sys_class_net)
        if mac_address:
            return mac_address

    raise ValueError("could not find a usable network interface MAC address")


def validate_topic_segment(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if not TOPIC_SEGMENT_PATTERN.fullmatch(text):
        raise ValueError(f"{name} must contain only letters, digits, underscore, or hyphen")
    return text


def validate_device_id(device_id: str) -> str:
    text = validate_topic_segment("MQTT_DEVICE_ID", device_id)
    if not DEVICE_ID_PATTERN.fullmatch(text):
        raise ValueError("MQTT_DEVICE_ID must match device_[0-9A-Fa-f]{4,12}")
    return text


def resolve_mqtt_device_id(
    *,
    env_device_id: Optional[str],
    mac_address: Optional[str] = None,
    preferred_interface: str = "",
    suffix_length: int = 4,
    sys_class_net: str = "/sys/class/net",
) -> str:
    if env_device_id:
        return validate_device_id(env_device_id)
    if mac_address:
        return mac_to_device_id(mac_address, suffix_length)
    primary_mac = find_primary_mac_address(
        preferred_interface=preferred_interface,
        sys_class_net=sys_class_net,
    )
    return mac_to_device_id(primary_mac, suffix_length)


def resolve_mqtt_username(env_username: Optional[str], device_id: str) -> str:
    username = str(env_username or device_id).strip()
    if username != device_id:
        raise ValueError("MQTT_USERNAME must equal MQTT_DEVICE_ID for EMQX per-device ACL")
    return validate_device_id(username)
