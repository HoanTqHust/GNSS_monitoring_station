"""
SDR Thread - BladeRF data capture with spectrogram BMP pipeline + AI classifier
Follows test.py pattern: reader_process -> queue -> plotter_process -> BMP
Classifier: gnss_jamming_classifier_mps.pth (6 classes)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import os
import queue as queue_module
import time
import threading
import multiprocessing as mp
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from flask_socketio import SocketIO
from matplotlib.colors import LinearSegmentedColormap
import matplotlib
matplotlib.use("Agg")

import sys

from config import config
from telemetry.mqtt_publisher import MqttPublishSettings, MqttTelemetryPublisher
from telemetry.mqtt_schema import (
    build_detect_sdr_message,
    build_raw_sdr_snapshot_chunk_message,
)

LOGGER = logging.getLogger("thread.sdr_thread")
LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "all.log")

# ══════════════════════════════════════════════
# CONFIG (mirror of legacy SDR pipeline)
# ══════════════════════════════════════════════
SAMPLE_RATE  = float(config.SDR_SAMPLE_RATE)
CENTER_FREQ  = float(config.SDR_FREQ)
GAIN         = float(config.SDR_GAIN)
BANDWIDTH    = float(config.SDR_BANDWIDTH)

BUFFER_SIZE  = int(config.SDR_NUM_SAMPLES)
NUM_BUFFERS  = 8

WINDOW_LEN   = 512
NOVERLAP     = 384
NFFT         = 512
FMIN_MHZ     = -15.0
FMAX_MHZ     =  15.0
DYN_RANGE_DB = 55

OUTPUT_DIR   = "./BKDATASET/"
IMG_W        = 640
IMG_H        = 480

THROTTLE_S    = 0.1
QUEUE_MAXSIZE = 32

MODEL_PATH = "/home/firefly/double_difference_cp/SDR/model/gnss_jamming_classifier_mps.pth"
CLASS_NAMES = ["Clean", "Narrowband", "Pulsed", "Swept", "Multi-tone", "Partial-band"]

# ══════════════════════════════════════════════
# COLORMAP
# ══════════════════════════════════════════════
_COLORS = [
    (0.00, "#000000"),
    (0.20, "#0d0d3a"),
    (0.38, "#1a1a8c"),
    (0.55, "#0055ff"),
    (0.68, "#00ccff"),
    (0.80, "#00ffcc"),
    (0.90, "#aaff00"),
    (0.97, "#ffff00"),
    (1.00, "#ffffff"),
]
_cmap = LinearSegmentedColormap.from_list(
    "sdr_waterfall", [(v, c) for v, c in _COLORS]
)
_LUT = (_cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)

# ══════════════════════════════════════════════
# MODEL — ResNet18 (matches trained weights)
# ══════════════════════════════════════════════
class BasicBlock(nn.Module):
    expansion = 1
    def __init__(self, in_channels, out_channels, stride=1, downsample=None):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=stride, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.downsample = downsample

    def forward(self, x):
        identity = x
        out = nn.functional.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        return nn.functional.relu(out + identity)


class ResNet18(nn.Module):
    def __init__(self, num_classes=6):
        super().__init__()
        self.in_channels = 64
        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        self.layer1 = self._make_layer(BasicBlock, 64, 2, stride=1)
        self.layer2 = self._make_layer(BasicBlock, 128, 2, stride=2)
        self.layer3 = self._make_layer(BasicBlock, 256, 2, stride=2)
        self.layer4 = self._make_layer(BasicBlock, 512, 2, stride=2)

        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512, num_classes)

    def _make_layer(self, block, out_channels, blocks, stride=1):
        downsample = None
        if stride != 1 or self.in_channels != out_channels:
            downsample = nn.Sequential(
                nn.Conv2d(self.in_channels, out_channels, 1, stride=stride, bias=False),
                nn.BatchNorm2d(out_channels),
            )
        layers = []
        layers.append(block(self.in_channels, out_channels, stride, downsample))
        self.in_channels = out_channels
        for _ in range(1, blocks):
            layers.append(block(out_channels, out_channels))
        return nn.Sequential(*layers)

    def forward(self, x):
        x = nn.functional.relu(self.bn1(self.conv1(x)))
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        x = self.fc(x)
        return x


def load_model():
    model = ResNet18(num_classes=6)
    state = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
    model.load_state_dict(state)
    model.eval()
    return model


def preprocess_image(img: Image.Image) -> torch.Tensor:
    img = img.resize((224, 224), Image.BILINEAR)
    arr = np.array(img).astype(np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)
    # Model was trained on raw 0-1 BMP pixels, no ImageNet normalization
    return torch.from_numpy(arr).unsqueeze(0).float()


def predict_image(model, img: Image.Image):
    with torch.no_grad():
        tensor = preprocess_image(img).float()
        logits = model(tensor)
        probs = torch.softmax(logits, dim=1)[0]
        conf, idx = torch.max(probs, dim=0)
        return CLASS_NAMES[idx.item()], conf.item(), probs.numpy()


# ══════════════════════════════════════════════
# HELPER — spectrogram
# ══════════════════════════════════════════════
def compute_spectrogram(x: np.ndarray) -> np.ndarray:
    x = x - x.mean()
    hop = WINDOW_LEN - NOVERLAP
    win = np.hanning(WINDOW_LEN).astype(np.float32)

    if len(x) < WINDOW_LEN:
        return np.zeros((NFFT, 1), dtype=np.float32)

    n_frm = 1 + (len(x) - WINDOW_LEN) // hop
    SY = np.empty((NFFT, n_frm), dtype=np.complex64)

    for k in range(n_frm):
        s = k * hop
        SY[:, k] = np.fft.fft(x[s:s + WINDOW_LEN] * win, n=NFFT)

    SY = np.fft.fftshift(SY, axes=0)
    FY = np.fft.fftshift(np.fft.fftfreq(NFFT, d=1.0 / SAMPLE_RATE)) / 1e6

    mask = (FY >= FMIN_MHZ) & (FY <= FMAX_MHZ)
    power_db = 10 * np.log10(np.abs(SY[mask]) ** 2 + 1e-12)
    return power_db


# ══════════════════════════════════════════════
# HELPER — render BMP
# ══════════════════════════════════════════════
def render_bmp(power_db: np.ndarray):
    vmax = np.percentile(power_db, 99.5)
    vmin = vmax - DYN_RANGE_DB

    denom = max(vmax - vmin, 1e-6)
    idx = np.clip((power_db - vmin) / denom, 0.0, 1.0)
    idx = (idx * 255).astype(np.uint8)
    idx = idx[::-1, :]

    rgb = _LUT[idx]
    return Image.fromarray(rgb, mode="RGB").resize((IMG_W, IMG_H), Image.BILINEAR)


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_jamming_state(state: str, confidence: float) -> bool:
    if state in {"Clean", "Unknown"}:
        return False
    return confidence >= config.SDR_JAMMING_CONFIDENCE_THRESHOLD


def _encode_png_base64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _estimate_ring_frames() -> int:
    frame_interval_s = max(THROTTLE_S, 0.001)
    pre_frames = math.ceil(max(0.0, config.SDR_SNAPSHOT_PRE_SECONDS) / frame_interval_s)
    return max(1, pre_frames + 2)


def _snapshot_metadata_base(file_id: str, detection: dict[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any]:
    raw_bytes = b"".join(frame["raw_bytes"] for frame in frames)
    sample_count = len(raw_bytes) // 4
    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    return {
        "file_id": file_id,
        "receiver": "sdr0",
        "sample_format": "sc16_q11",
        "center_freq_hz": int(CENTER_FREQ),
        "sample_rate_hz": int(SAMPLE_RATE),
        "gain_db": float(GAIN),
        "bandwidth_hz": int(BANDWIDTH),
        "band": "L1",
        "requested_pre_seconds": float(config.SDR_SNAPSHOT_PRE_SECONDS),
        "requested_post_seconds": float(config.SDR_SNAPSHOT_POST_SECONDS),
        "frame_count": len(frames),
        "sample_count": sample_count,
        "file_bytes": len(raw_bytes),
        "file_sha256": file_sha256,
        "first_frame_utc": frames[0]["captured_at_utc"] if frames else None,
        "last_frame_utc": frames[-1]["captured_at_utc"] if frames else None,
        **detection,
    }


def _save_sdr_snapshot(
    *,
    file_id: str,
    detection: dict[str, Any],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    os.makedirs(config.SDR_SNAPSHOT_DIR, exist_ok=True)
    raw_bytes = b"".join(frame["raw_bytes"] for frame in frames)
    metadata = _snapshot_metadata_base(file_id, detection, frames)
    bin_path = os.path.join(config.SDR_SNAPSHOT_DIR, f"{file_id}.bin")
    json_path = os.path.join(config.SDR_SNAPSHOT_DIR, f"{file_id}.json")
    with open(bin_path, "wb") as bin_file:
        bin_file.write(raw_bytes)
    metadata["bin_path"] = bin_path
    metadata["metadata_path"] = json_path
    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump(metadata, json_file, ensure_ascii=False, sort_keys=True, indent=2)
    return metadata


def _validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _complex64_to_sc16_q11_bytes(samples: np.ndarray) -> bytes:
    if samples is None:
        raise ValueError("samples must not be None")
    complex_samples = np.asarray(samples, dtype=np.complex64)
    clipped_real = np.clip(np.real(complex_samples), -1.0, 1.0)
    clipped_imag = np.clip(np.imag(complex_samples), -1.0, 1.0)
    interleaved = np.empty(complex_samples.size * 2, dtype="<i2")
    interleaved[0::2] = np.rint(clipped_real * 2047.0).astype("<i2")
    interleaved[1::2] = np.rint(clipped_imag * 2047.0).astype("<i2")
    return interleaved.tobytes()


def _metadata_error_text(metadata: Any) -> str | None:
    error_code = getattr(metadata, "error_code", None)
    if error_code is None:
        return None
    text = str(error_code).lower()
    if text in {"0", "none", "rxmetadataerrorcode.none", "rx_metadata_error_code.none"}:
        return None
    if text.endswith(".none") or text.endswith("_none"):
        return None
    return str(error_code)


def _call_usrp_config(method: Any, value: Any, channel: int) -> None:
    try:
        method(value, channel)
    except TypeError:
        method(value)


def _set_usrp_rx_freq(usrp: Any, uhd_module: Any, freq_hz: float, channel: int) -> None:
    tune_request_cls = getattr(getattr(uhd_module, "types", None), "TuneRequest", None)
    if tune_request_cls is None:
        _call_usrp_config(usrp.set_rx_freq, freq_hz, channel)
        return
    tune_request = tune_request_cls(float(freq_hz))
    _call_usrp_config(usrp.set_rx_freq, tune_request, channel)


def _ensure_child_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for handler in root_logger.handlers:
        if (
            isinstance(handler, logging.FileHandler)
            and os.path.abspath(getattr(handler, "baseFilename", "")) == LOG_PATH
        ):
            return
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root_logger.addHandler(handler)


class BladeRfReceiverSource:
    def __init__(self) -> None:
        sys.path.insert(0, "/home/firefly/double_difference_cp/SDR")
        from src import BladeRFSdr, Receiver

        _validate_positive("SDR_SAMPLE_RATE", SAMPLE_RATE)
        _validate_positive("SDR_BANDWIDTH", BANDWIDTH)
        self._sdr = BladeRFSdr(device_string=config.SDR_DEVICE)
        self._sdr.config_rx(
            freq=CENTER_FREQ,
            sr=SAMPLE_RATE,
            gain=GAIN,
            bw=BANDWIDTH,
        )
        self._receiver = Receiver(self._sdr)
        LOGGER.info(
            "sdr_source_started source=bladerf device=%s freq_hz=%s sample_rate_hz=%s gain_db=%s bandwidth_hz=%s",
            config.SDR_DEVICE,
            CENTER_FREQ,
            SAMPLE_RATE,
            GAIN,
            BANDWIDTH,
        )

    def receive_with_raw(self, num_samples: int) -> tuple[np.ndarray, bytes]:
        return self._receiver.receive_with_raw(num_samples)

    def close(self) -> None:
        self._sdr.close()


class UhdUsrpReceiverSource:
    def __init__(self, uhd_module: Any | None = None) -> None:
        _validate_positive("SDR_SAMPLE_RATE", SAMPLE_RATE)
        _validate_positive("SDR_BANDWIDTH", BANDWIDTH)
        if config.SDR_USRP_CHANNEL < 0:
            raise ValueError("SDR_USRP_CHANNEL must be non-negative")
        if not config.SDR_USRP_ARGS:
            raise ValueError("SDR_USRP_ARGS must not be empty for USRP sources")

        if uhd_module is None:
            try:
                import uhd as uhd_module
            except ImportError as exc:
                raise RuntimeError(
                    "UHD Python module is required for SDR_SOURCE=usrp_x300. "
                    "Install UHD with Python API enabled on the RK3588 host."
                ) from exc

        self._uhd = uhd_module
        self._channel = int(config.SDR_USRP_CHANNEL)
        self._recv_timeout_s = float(config.SDR_USRP_RECV_TIMEOUT)
        _validate_positive("SDR_USRP_RECV_TIMEOUT", self._recv_timeout_s)

        self._usrp = self._uhd.usrp.MultiUSRP(config.SDR_USRP_ARGS)
        _call_usrp_config(self._usrp.set_rx_rate, SAMPLE_RATE, self._channel)
        _set_usrp_rx_freq(self._usrp, self._uhd, CENTER_FREQ, self._channel)
        _call_usrp_config(self._usrp.set_rx_gain, GAIN, self._channel)
        if config.SDR_USRP_SET_BANDWIDTH and hasattr(self._usrp, "set_rx_bandwidth"):
            _call_usrp_config(self._usrp.set_rx_bandwidth, BANDWIDTH, self._channel)
        elif hasattr(self._usrp, "set_rx_bandwidth"):
            LOGGER.info(
                "usrp_rx_bandwidth_not_set requested_bandwidth_hz=%s reason=SDR_USRP_SET_BANDWIDTH_false",
                BANDWIDTH,
            )
        if config.SDR_USRP_ANTENNA:
            _call_usrp_config(self._usrp.set_rx_antenna, config.SDR_USRP_ANTENNA, self._channel)

        stream_args = self._uhd.usrp.StreamArgs("fc32", "sc16")
        stream_args.channels = [self._channel]
        if config.SDR_USRP_STREAM_ARGS:
            stream_args.args = config.SDR_USRP_STREAM_ARGS
        self._rx_streamer = self._usrp.get_rx_stream(stream_args)
        self._metadata = self._uhd.types.RXMetadata()
        max_samps = int(self._rx_streamer.get_max_num_samps())
        if max_samps <= 0:
            raise RuntimeError("UHD RX streamer returned non-positive max samples")
        self._recv_buffer = np.zeros(max_samps, dtype=np.complex64)
        self._start_stream()
        LOGGER.info(
            "sdr_source_started source=usrp_x300 args=%s freq_hz=%s sample_rate_hz=%s gain_db=%s bandwidth_hz=%s channel=%s antenna=%s stream_args=%s",
            config.SDR_USRP_ARGS,
            CENTER_FREQ,
            SAMPLE_RATE,
            GAIN,
            BANDWIDTH,
            self._channel,
            config.SDR_USRP_ANTENNA or "<default>",
            config.SDR_USRP_STREAM_ARGS or "<default>",
        )

    def _start_stream(self) -> None:
        stream_cmd = self._uhd.types.StreamCMD(self._uhd.types.StreamMode.start_cont)
        stream_cmd.stream_now = True
        self._rx_streamer.issue_stream_cmd(stream_cmd)

    def receive_with_raw(self, num_samples: int) -> tuple[np.ndarray, bytes]:
        if num_samples <= 0:
            raise ValueError("num_samples must be positive")

        samples = np.empty(num_samples, dtype=np.complex64)
        received = 0
        deadline = time.monotonic() + self._recv_timeout_s
        while received < num_samples:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"USRP RX timeout received={received} requested={num_samples}"
                )

            chunk_len = min(num_samples - received, self._recv_buffer.size)
            view = self._recv_buffer[:chunk_len]
            try:
                count = self._rx_streamer.recv(view, self._metadata, self._recv_timeout_s)
            except TypeError:
                count = self._rx_streamer.recv(view, self._metadata)

            error_text = _metadata_error_text(self._metadata)
            if error_text is not None:
                LOGGER.warning("usrp_rx_metadata_error error=%s", error_text)

            count = int(count)
            if count <= 0:
                continue
            samples[received : received + count] = view[:count]
            received += count

        return samples, _complex64_to_sc16_q11_bytes(samples)

    def close(self) -> None:
        try:
            stream_cmd = self._uhd.types.StreamCMD(self._uhd.types.StreamMode.stop_cont)
            self._rx_streamer.issue_stream_cmd(stream_cmd)
        except Exception:
            LOGGER.exception("usrp_stop_stream_error")


def _open_sdr_receiver_source():
    source = str(config.SDR_SOURCE).strip().lower()
    if source in {"usrp_x300", "usrp", "x300"}:
        return UhdUsrpReceiverSource()
    if source in {"bladerf", "blade_rf"}:
        return BladeRfReceiverSource()
    raise ValueError(f"Unsupported SDR_SOURCE: {config.SDR_SOURCE}")


# ══════════════════════════════════════════════
# PROCESS A — reader
# ══════════════════════════════════════════════
def reader_process(queue: mp.Queue, stop_event: mp.Event):
    _ensure_child_logging()
    receiver_source = None

    last_push_t = 0.0
    chunks = []
    raw_chunks = []

    try:
        LOGGER.info(
            "sdr_reader_starting source=%s throttle_ms=%s buffer_size=%s num_buffers=%s",
            config.SDR_SOURCE,
            THROTTLE_S * 1000,
            BUFFER_SIZE,
            NUM_BUFFERS,
        )
        receiver_source = _open_sdr_receiver_source()
        LOGGER.info("sdr_reader_started source=%s", config.SDR_SOURCE)
        while not stop_event.is_set():
            raw_samples, raw_bytes = receiver_source.receive_with_raw(BUFFER_SIZE)
            iq = raw_samples.astype(np.complex64)

            chunks.append(iq)
            raw_chunks.append(raw_bytes)
            if len(chunks) > NUM_BUFFERS:
                chunks.pop(0)
            if len(raw_chunks) > NUM_BUFFERS:
                raw_chunks.pop(0)

            now = time.monotonic()
            if now - last_push_t >= THROTTLE_S and len(chunks) == NUM_BUFFERS:
                frame = np.concatenate(chunks).astype(np.complex64)
                raw_frame = b"".join(raw_chunks)
                try:
                    queue.put_nowait({
                        "samples": frame,
                        "raw_bytes": raw_frame,
                        "captured_at_utc": _utc_now_z(),
                    })
                except Exception:
                    LOGGER.warning("sdr_reader_queue_drop")
                last_push_t = now

    except Exception:
        LOGGER.exception("sdr_reader_process_error")
    finally:
        if receiver_source is not None:
            try:
                receiver_source.close()
            except Exception:
                LOGGER.exception("sdr_reader_close_error")
        LOGGER.info("sdr_reader_stopped")


# ══════════════════════════════════════════════
# PROCESS B — plotter + classifier
# ══════════════════════════════════════════════
def plotter_process(queue: mp.Queue, stop_event: mp.Event, result_queue: mp.Queue):
    _ensure_child_logging()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load model in this process
    model = None
    try:
        model = load_model()
        LOGGER.info("sdr_classifier_model_loaded path=%s", MODEL_PATH)
    except Exception:
        LOGGER.exception("sdr_classifier_model_load_error path=%s", MODEL_PATH)

    frame_idx = 0
    t0 = time.time()
    cnt = 0
    raw_ring = deque(maxlen=_estimate_ring_frames())
    pending_snapshot: dict[str, Any] | None = None
    next_snapshot_allowed_at = 0.0

    LOGGER.info("sdr_plotter_started output_dir=%s", OUTPUT_DIR)

    while not stop_event.is_set():
        try:
            item = queue.get(timeout=2.0)
        except Exception:
            continue

        try:
            if isinstance(item, dict):
                x = item["samples"]
                raw_bytes = item.get("raw_bytes", b"")
                captured_at_utc = item.get("captured_at_utc") or _utc_now_z()
            else:
                x = item
                raw_bytes = b""
                captured_at_utc = _utc_now_z()

            raw_record = {
                "frame_idx": frame_idx,
                "captured_at_utc": captured_at_utc,
                "raw_bytes": raw_bytes,
            }
            raw_ring.append(raw_record)

            power_db = compute_spectrogram(x)
            img = render_bmp(power_db)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(OUTPUT_DIR, f"{ts}_{frame_idx:06d}.bmp")
            img.save(path, format="BMP")

            # Classify if model loaded
            state = "Unknown"
            confidence = 0.0
            probs = None
            if model is not None:
                try:
                    state, confidence, probs = predict_image(model, img)
                except Exception:
                    LOGGER.exception("sdr_classifier_inference_error frame_idx=%s", frame_idx)

            detected_at_utc = _utc_now_z()
            mqtt_event = None
            created_pending = False
            if (
                raw_bytes
                and pending_snapshot is None
                and time.monotonic() >= next_snapshot_allowed_at
                and _is_jamming_state(state, confidence)
            ):
                file_id = f"sdr-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
                detection = {
                    "jamming": True,
                    "class": state,
                    "confidence": confidence,
                    "probs": probs.tolist() if probs is not None else None,
                    "class_names": list(CLASS_NAMES),
                    "frame_idx": frame_idx,
                    "detected_at_utc": detected_at_utc,
                    "created_at_utc": detected_at_utc,
                    "spectrum_image_base64": _encode_png_base64(img),
                    "image_encoding": "png_base64",
                }
                pending_snapshot = {
                    "file_id": file_id,
                    "detection": detection,
                    "frames": list(raw_ring),
                    "post_until_monotonic": time.monotonic() + max(0.0, config.SDR_SNAPSHOT_POST_SECONDS),
                }
                created_pending = True
                LOGGER.info(
                    "sdr_snapshot_started file_id=%s class=%s confidence=%s",
                    file_id,
                    state,
                    confidence,
                )
            elif pending_snapshot is not None and raw_bytes:
                pending_snapshot["frames"].append(raw_record)

            if pending_snapshot is not None:
                should_finalize = time.monotonic() >= pending_snapshot["post_until_monotonic"]
                if should_finalize and (not created_pending or config.SDR_SNAPSHOT_POST_SECONDS <= 0):
                    snapshot = _save_sdr_snapshot(
                        file_id=pending_snapshot["file_id"],
                        detection=pending_snapshot["detection"],
                        frames=pending_snapshot["frames"],
                    )
                    mqtt_payload = {**pending_snapshot["detection"], **snapshot}
                    chunk_count = max(1, math.ceil(snapshot["file_bytes"] / max(1, config.SDR_MQTT_CHUNK_BYTES)))
                    mqtt_payload["chunk_count"] = chunk_count
                    mqtt_event = {
                        "type": "sdr_threat_snapshot",
                        "seq": int(pending_snapshot["detection"]["frame_idx"]),
                        "created_at_utc": _utc_now_z(),
                        "payload": mqtt_payload,
                    }
                    next_snapshot_allowed_at = time.monotonic() + max(0.0, config.SDR_SNAPSHOT_COOLDOWN_SECONDS)
                    LOGGER.info(
                        "sdr_snapshot_saved file_id=%s bytes=%s chunks=%s",
                        snapshot["file_id"],
                        snapshot["file_bytes"],
                        chunk_count,
                    )
                    pending_snapshot = None

            # Put result for main thread to emit via socketio
            if result_queue is not None:
                try:
                    result = {
                        "class": state,
                        "confidence": confidence,
                        "probs": probs.tolist() if probs is not None else None,
                        "frame_idx": frame_idx,
                        "filename": path,
                    }
                    if mqtt_event is not None:
                        result["mqtt_event"] = mqtt_event
                    result_queue.put_nowait(result)
                except Exception:
                    LOGGER.warning("sdr_result_queue_drop frame_idx=%s", frame_idx)

            frame_idx += 1
            cnt += 1

            elapsed = time.time() - t0
            if elapsed >= 5.0:
                LOGGER.info("sdr_plotter_fps fps=%.2f total_frames=%s", cnt / elapsed, frame_idx)
                t0 = time.time()
                cnt = 0
        except Exception:
            LOGGER.exception("sdr_plotter_process_error frame_idx=%s", frame_idx)

    LOGGER.info("sdr_plotter_stopped total_frames=%s", frame_idx)


# ══════════════════════════════════════════════
# SDRThread
# ══════════════════════════════════════════════
class SDRThread:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.running = False
        self.processes = []
        self.queue = None
        self.stop_event = None
        self.result_queue = None
        self.mqtt_event_queue = None
        self.mqtt_thread = None
        self.result_thread = None

    @staticmethod
    def get_instance(socketio: SocketIO) -> "SDRThread":
        with SDRThread._lock:
            if SDRThread._instance is None:
                SDRThread._instance = SDRThread(socketio)
            return SDRThread._instance

    def start(self) -> None:
        """Start the SDR capture pipeline (reader + plotter/classifier processes)"""
        if self.running:
            LOGGER.warning("SDR thread already running")
            return

        self.running = True
        self.queue = mp.Queue(maxsize=QUEUE_MAXSIZE)
        self.result_queue = mp.Queue(maxsize=QUEUE_MAXSIZE)
        self.mqtt_event_queue = queue_module.Queue(maxsize=config.SDR_MQTT_QUEUE_SIZE)
        self.stop_event = mp.Event()

        p_reader = mp.Process(
            target=reader_process,
            args=(self.queue, self.stop_event),
            daemon=True
        )
        p_plotter = mp.Process(
            target=plotter_process,
            args=(self.queue, self.stop_event, self.result_queue),
            daemon=True
        )

        p_reader.start()
        p_plotter.start()

        self.processes = [p_reader, p_plotter]

        # Start result consumer thread
        self.result_thread = threading.Thread(target=self._result_consumer, daemon=True)
        self.result_thread.start()
        self.mqtt_thread = threading.Thread(
            target=self._mqtt_event_worker,
            daemon=True,
            name="sdr-mqtt-publisher-worker",
        )
        self.mqtt_thread.start()

        LOGGER.info("SDR pipeline started (reader + plotter/classifier)")

    def _result_consumer(self):
        """Consume classification results and emit via socketio"""
        while self.running and not self.stop_event.is_set():
            try:
                if self.result_queue is None:
                    break
                result = self.result_queue.get(timeout=0.5)
            except queue_module.Empty:
                continue
            except Exception:
                LOGGER.exception("sdr_result_consumer_read_error")
                continue

            try:
                self.socketio.emit("sdr_classify", {
                    "class": result["class"],
                    "confidence": result["confidence"],
                    "probs": result["probs"],
                    "frame_idx": result["frame_idx"],
                    "filename": result["filename"],
                })
                mqtt_event = result.get("mqtt_event")
                if mqtt_event is not None and self.mqtt_event_queue is not None:
                    try:
                        self.mqtt_event_queue.put_nowait(mqtt_event)
                    except queue_module.Full:
                        LOGGER.warning(
                            "sdr_mqtt_queue_drop file_id=%s",
                            mqtt_event.get("payload", {}).get("file_id"),
                        )
            except Exception:
                LOGGER.exception("sdr_result_consumer_error")
                continue

    def _mqtt_event_worker(self) -> None:
        publisher = MqttTelemetryPublisher(MqttPublishSettings.from_config(config, "sdr"))
        LOGGER.info("sdr_mqtt_worker_started queue_maxsize=%s", config.SDR_MQTT_QUEUE_SIZE)
        while self.running and self.stop_event is not None and not self.stop_event.is_set():
            try:
                if self.mqtt_event_queue is None:
                    break
                event = self.mqtt_event_queue.get(timeout=0.5)
            except queue_module.Empty:
                continue
            except Exception:
                LOGGER.exception("sdr_mqtt_worker_read_error")
                continue

            try:
                if event.get("type") == "sdr_threat_snapshot":
                    self._publish_sdr_threat_snapshot(publisher, event)
                else:
                    LOGGER.warning("sdr_mqtt_unknown_event type=%s", event.get("type"))
            except Exception:
                LOGGER.exception(
                    "sdr_mqtt_publish_error file_id=%s",
                    event.get("payload", {}).get("file_id"),
                )

    def _publish_sdr_threat_snapshot(
        self,
        publisher: MqttTelemetryPublisher,
        event: dict[str, Any],
    ) -> None:
        payload = event["payload"]
        detect_topic, detect_message = build_detect_sdr_message(
            event,
            topic_prefix=config.MQTT_TOPIC_PREFIX,
            site_id=config.MQTT_SITE_ID,
            device_id=config.MQTT_DEVICE_ID,
        )
        if publisher.publish(detect_topic, detect_message):
            LOGGER.info(
                "sdr_detect_published topic=%s file_id=%s class=%s confidence=%s",
                detect_topic,
                payload.get("file_id"),
                payload.get("class"),
                payload.get("confidence"),
            )

        bin_path = payload.get("bin_path")
        if not bin_path:
            LOGGER.warning("sdr_snapshot_missing_bin_path file_id=%s", payload.get("file_id"))
            return

        chunk_bytes = max(1, int(config.SDR_MQTT_CHUNK_BYTES))
        file_size = int(payload.get("file_bytes", 0))
        chunk_count = max(1, math.ceil(file_size / chunk_bytes))
        with open(bin_path, "rb") as bin_file:
            for chunk_index in range(chunk_count):
                chunk = bin_file.read(chunk_bytes)
                chunk_payload = {
                    **payload,
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                    "chunk_bytes": len(chunk),
                    "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
                    "chunk_base64": base64.b64encode(chunk).decode("ascii"),
                }
                chunk_event = {
                    "seq": int(event.get("seq", payload.get("frame_idx", 0))),
                    "created_at_utc": event.get("created_at_utc"),
                    "payload": chunk_payload,
                }
                raw_topic, raw_message = build_raw_sdr_snapshot_chunk_message(
                    chunk_event,
                    topic_prefix=config.MQTT_TOPIC_PREFIX,
                    site_id=config.MQTT_SITE_ID,
                    device_id=config.MQTT_DEVICE_ID,
                )
                publisher.publish(raw_topic, raw_message, wait_for_ack=False)
        LOGGER.info(
            "sdr_raw_snapshot_chunks_published file_id=%s chunks=%s bytes=%s",
            payload.get("file_id"),
            chunk_count,
            file_size,
        )

    def stop(self) -> None:
        """Stop the SDR capture pipeline"""
        self.running = False
        if self.stop_event:
            self.stop_event.set()

        for p in self.processes:
            if p.is_alive():
                p.join(timeout=2.0)

        self.processes = []
        LOGGER.info("SDR pipeline stopped")

    @property
    def is_running(self) -> bool:
        return self.running and any(p.is_alive() for p in self.processes)
