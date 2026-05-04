import os
from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return float(value)


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

    RAM_INGRESS_QUEUE_SIZE = int(os.environ.get("RAM_INGRESS_QUEUE_SIZE", 5000))

    RAM_DETECT_QUEUE_SIZE = int(os.environ.get("RAM_DETECT_QUEUE_SIZE", 2000))

    RAM_RAW_QUEUE_SIZE = int(os.environ.get("RAM_RAW_QUEUE_SIZE", 5000))

    RAM_QUEUE_POLL_INTERVAL = float(os.environ.get("RAM_QUEUE_POLL_INTERVAL", 0.02))

    RAM_RAW_EMIT_BATCH_SIZE = int(os.environ.get("RAM_RAW_EMIT_BATCH_SIZE", 100))

    # Realtime detector test thresholds (to avoid perpetual "Pending").
    SOS_CARRIER_THRESHOLD = _env_float("SOS_CARRIER_THRESHOLD", 0.09)
    SOS_SMOOTHED_PSEUDORANGE_THRESHOLD = _env_float(
        "SOS_SMOOTHED_PSEUDORANGE_THRESHOLD",
        1.10,
    )
    D3_CARRIER_SIMILARITY_THRESHOLD = _env_float(
        "D3_CARRIER_SIMILARITY_THRESHOLD",
        0.0,
    )
    D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD = _env_float(
        "D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD",
        0.0,
    )
    D3_MIN_CLUSTER_SIZE = int(os.environ.get("D3_MIN_CLUSTER_SIZE", 3))
