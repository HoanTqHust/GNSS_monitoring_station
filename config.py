import os
from dotenv import load_dotenv

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
    MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "rw_user")
    MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "rw")
    MQTT_CLIENT_ID_PREFIX = os.environ.get("MQTT_CLIENT_ID_PREFIX", "double-difference-cp")
    MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "gnss")
    MQTT_SITE_ID = os.environ.get("MQTT_SITE_ID", "default_site")
    MQTT_DEVICE_ID = os.environ.get("MQTT_DEVICE_ID", "test_device")
    MQTT_QOS = int(os.environ.get("MQTT_QOS", 1))
    MQTT_KEEPALIVE_S = int(os.environ.get("MQTT_KEEPALIVE_S", 60))
    MQTT_PUBLISH_TIMEOUT_S = _env_float("MQTT_PUBLISH_TIMEOUT_S", 2.0)
    MQTT_POSITION_RETAIN = _env_bool("MQTT_POSITION_RETAIN", False)
