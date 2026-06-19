import os
from dotenv import load_dotenv

from telemetry.mqtt_identity import (
    find_primary_mac_address as _find_primary_mac_address,
    mac_to_device_id as _mac_to_device_id,
    normalize_mac_address as _normalize_mac_address,
    read_mac_from_interface as _read_mac_from_interface,
    resolve_mqtt_device_id as _resolve_mqtt_device_id,
    resolve_mqtt_username as _resolve_mqtt_username,
    validate_device_id as _validate_device_id,
    validate_topic_segment as _validate_topic_segment,
)

load_dotenv()


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_csv_set(name: str, default: str):
    value = os.environ.get(name)
    text = default if value is None or value.strip() == "" else value
    if text.strip() == "*":
        return None
    items = frozenset(item.strip() for item in text.split(",") if item.strip())
    if not items:
        raise ValueError(f"{name} must not be empty; use * to allow every identity")
    return items


class config:
     
    PORT1 = os.environ.get("PORT1", "/dev/ttyACM0")
    
    PORT2 = os.environ.get("PORT2", "/dev/ttyACM1")
    
    PORT3 = os.environ.get("PORT3", "/dev/ttyACM2")
    
    # BUFFER_SAMPLES = int(os.environ.get("BUFFER_SAMPLES", 30))
    BUFFER_SAMPLES = int(os.environ.get("BUFFER_SAMPLES", 150))
    
    PLOT_INTERVAL = float(os.environ.get("PLOT_INTERVAL", 2.0))
    
    FIX = int(os.environ.get("FIX", 0))
    
    HOSTSOCKET = os.environ.get("HOSTSOCKET", "0.0.0.0")
    
    PORTSOCKET = int(os.environ.get("PORTSOCKET", 5000))
    
    ELE_MASK = int(os.environ.get("ELE_MASK", 15))

    RAM_INGRESS_QUEUE_SIZE = int(os.environ.get("RAM_INGRESS_QUEUE_SIZE", 500000))

    RAM_DETECT_QUEUE_SIZE = int(os.environ.get("RAM_DETECT_QUEUE_SIZE", 200000))

    RAM_RAW_QUEUE_SIZE = int(os.environ.get("RAM_RAW_QUEUE_SIZE", 500000))
    RAM_RAW_MQTT_QUEUE_SIZE = int(os.environ.get("RAM_RAW_MQTT_QUEUE_SIZE", 200000))

    RAM_QUEUE_POLL_INTERVAL = float(os.environ.get("RAM_QUEUE_POLL_INTERVAL", 0.02))

    RAM_RAW_EMIT_BATCH_SIZE = int(os.environ.get("RAM_RAW_EMIT_BATCH_SIZE", 100))
    RAM_HEALTH_PUBLISH_INTERVAL = _env_float("RAM_HEALTH_PUBLISH_INTERVAL", 1.0)
    RAW_UBX_ALLOWED_IDENTITIES = _env_csv_set(
        "RAW_UBX_ALLOWED_IDENTITIES",
        "RXM-RAWX,NAV-PVT,NAV-SAT,MON-SPAN",
    )

    # Realtime detector test thresholds (to avoid perpetual "Pending").
    SOS_CARRIER_THRESHOLD = _env_float("SOS_CARRIER_THRESHOLD", 0.04)
    SOS_SMOOTHED_PSEUDORANGE_THRESHOLD = _env_float(
        "SOS_SMOOTHED_PSEUDORANGE_THRESHOLD",
        1.10,
    )
    D3_CARRIER_SIMILARITY_THRESHOLD = _env_float(
        "D3_CARRIER_SIMILARITY_THRESHOLD",
        0.001,
    )
    D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD = _env_float(
        "D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD",
        0.001,
    )
    D3_MIN_CLUSTER_SIZE = int(os.environ.get("D3_MIN_CLUSTER_SIZE", 3))

    MQTT_ENABLED = _env_bool("MQTT_ENABLED", True)
    MQTT_HOST = os.environ.get("MQTT_HOST", "gnss.soict.io")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
    MQTT_DEVICE_MAC_INTERFACE = os.environ.get("MQTT_DEVICE_MAC_INTERFACE", "")
    MQTT_DEVICE_MAC_SUFFIX_LENGTH = int(os.environ.get("MQTT_DEVICE_MAC_SUFFIX_LENGTH", 4))
    MQTT_DEVICE_ID = _resolve_mqtt_device_id(
        env_device_id=os.environ.get("MQTT_DEVICE_ID"),
        mac_address=os.environ.get("MQTT_DEVICE_MAC"),
        preferred_interface=MQTT_DEVICE_MAC_INTERFACE,
        suffix_length=MQTT_DEVICE_MAC_SUFFIX_LENGTH,
    )
    MQTT_USERNAME = _resolve_mqtt_username(os.environ.get("MQTT_USERNAME"), MQTT_DEVICE_ID)
    MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
    MQTT_CLIENT_ID_PREFIX = os.environ.get("MQTT_CLIENT_ID_PREFIX", "double-difference-cp")
    MQTT_TOPIC_PREFIX = _validate_topic_segment("MQTT_TOPIC_PREFIX", os.environ.get("MQTT_TOPIC_PREFIX", "gnss"))
    MQTT_SITE_ID = _validate_topic_segment("MQTT_SITE_ID", os.environ.get("MQTT_SITE_ID", "default_site"))
    MQTT_QOS = int(os.environ.get("MQTT_QOS", 1))
    MQTT_KEEPALIVE_S = int(os.environ.get("MQTT_KEEPALIVE_S", 60))
    MQTT_PUBLISH_TIMEOUT_S = _env_float("MQTT_PUBLISH_TIMEOUT_S", 2.0)
    MQTT_POSITION_RETAIN = _env_bool("MQTT_POSITION_RETAIN", False)

    # SDR Config
    SDR_SOURCE = os.environ.get("SDR_SOURCE", "usrp_x300")
    SDR_DEVICE = os.environ.get("SDR_DEVICE", "libusb:device=6:3")
    SDR_USRP_ADDR = os.environ.get("SDR_USRP_ADDR", "192.168.5.111")
    SDR_USRP_ARGS = os.environ.get("SDR_USRP_ARGS", f"addr={SDR_USRP_ADDR}")
    SDR_USRP_CHANNEL = int(os.environ.get("SDR_USRP_CHANNEL", 0))
    SDR_USRP_ANTENNA = os.environ.get("SDR_USRP_ANTENNA", "")
    SDR_USRP_STREAM_ARGS = os.environ.get("SDR_USRP_STREAM_ARGS", "")
    SDR_USRP_RECV_TIMEOUT = _env_float("SDR_USRP_RECV_TIMEOUT", 1.0)
    SDR_USRP_SET_BANDWIDTH = _env_bool("SDR_USRP_SET_BANDWIDTH", False)
    SDR_FREQ = _env_float("SDR_FREQ", 1575.42e6)  # GPS L1
    SDR_SAMPLE_RATE = _env_float("SDR_SAMPLE_RATE", 5e6)  # 5 MHz
    SDR_GAIN = _env_float("SDR_GAIN", 30)  # dB
    SDR_BANDWIDTH = _env_float("SDR_BANDWIDTH", 2.5e6)  # Hz
    SDR_NUM_SAMPLES = int(os.environ.get("SDR_NUM_SAMPLES", 8192))
    SDR_ENABLED = _env_bool("SDR_ENABLED", True)
    SDR_SNAPSHOT_PRE_SECONDS = _env_float("SDR_SNAPSHOT_PRE_SECONDS", 1.0)
    SDR_SNAPSHOT_POST_SECONDS = _env_float("SDR_SNAPSHOT_POST_SECONDS", 2.0)
    SDR_JAMMING_CONFIDENCE_THRESHOLD = _env_float("SDR_JAMMING_CONFIDENCE_THRESHOLD", 0.90)
    SDR_MQTT_CHUNK_BYTES = int(os.environ.get("SDR_MQTT_CHUNK_BYTES", 65536))
    SDR_SNAPSHOT_DIR = os.environ.get("SDR_SNAPSHOT_DIR", "output_sdr")
    SDR_SNAPSHOT_COOLDOWN_SECONDS = _env_float("SDR_SNAPSHOT_COOLDOWN_SECONDS", 5.0)
    SDR_MQTT_QUEUE_SIZE = int(os.environ.get("SDR_MQTT_QUEUE_SIZE", 256))
