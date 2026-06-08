from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


GNSS_NAMES = {
    0: ("GPS", "G"),
    1: ("SBAS", "S"),
    2: ("GALILEO", "E"),
    3: ("BEIDOU", "C"),
    5: ("QZSS", "J"),
    6: ("GLONASS", "R"),
}


SIGNAL_NAMES = {
    (0, 0): "L1C",
    (0, 3): "L2CL",
    (0, 4): "L2CM",
    (2, 0): "E1",
    (3, 0): "B1I",
    (6, 0): "L1",
}


def utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_utc(value: Any) -> str:
    if not value:
        return utc_now_z()
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        if text.endswith("Z"):
            return text
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_topic(prefix: str, site_id: str, device_id: str, suffix: str) -> str:
    parts = [prefix.strip("/"), site_id.strip("/"), device_id.strip("/"), suffix.strip("/")]
    if any(not part for part in parts):
        raise ValueError("MQTT topic parts must not be empty")
    return "/".join(parts)


def build_event_id(device_id: str, seq: int, suffix: str = "") -> str:
    suffix_part = f"-{suffix}" if suffix else ""
    return f"{device_id}-{int(seq):012d}{suffix_part}"


def build_command_branch_message(
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
    seq: int,
) -> list[tuple[str, dict[str, Any]]]:
    now = utc_now_z()
    envelope_base = {
        "seq": int(seq),
        "device_id": device_id,
        "site_id": site_id,
        "frontend": "ublox",
        "event_time": now,
        "ingest_time": now,
    }

    commands = [
        ("cmd/init/v1", {
            **envelope_base,
            "schema": "gnss.cmd.init.v1",
            "source": "pipeline",
            "event_id": build_event_id(device_id, seq, "cmd_init"),
            "data": {
                "status": "online",
                "ready": True,
            },
        }),
        ("cmd/ack/v1", {
            **envelope_base,
            "schema": "gnss.cmd.ack.v1",
            "source": "pipeline",
            "event_id": build_event_id(device_id, seq, "cmd_ack"),
            "data": {
                "acknowledged": [],
            },
        }),
    ]

    return [
        (build_topic(topic_prefix, site_id, device_id, suffix), msg)
        for suffix, msg in commands
    ]


def build_ack_message(
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
    acknowledged: list[str],
    extra_data: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    now = utc_now_z()
    data: dict[str, Any] = {"acknowledged": acknowledged}
    if extra_data:
        data["result"] = extra_data

    message = {
        "schema": "gnss.cmd.ack.v1",
        "event_id": build_event_id(device_id, int(time.time() * 1000), "cmd_ack"),
        "seq": int(time.time() * 1000),
        "device_id": device_id,
        "site_id": site_id,
        "frontend": "ublox",
        "source": "pipeline",
        "event_time": now,
        "ingest_time": now,
        "data": data,
    }
    topic = build_topic(topic_prefix, site_id, device_id, "cmd/ack/v1")
    return topic, message


def build_ublox_command_message(
    *,
    command_type: str,
    command_id: str,
    site_id: str,
    device_id: str,
    params: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    now = utc_now_z()
    message = {
        "schema": f"gnss.cmd.ublox.{command_type}.v1",
        "event_id": build_event_id(device_id, int(time.time() * 1000), f"cmd_{command_type}"),
        "seq": int(time.time() * 1000),
        "device_id": device_id,
        "site_id": site_id,
        "frontend": "ublox",
        "source": "server",
        "event_time": now,
        "ingest_time": now,
        "data": {
            "command_id": command_id,
            "command_type": command_type,
            "params": params,
        },
    }
    topic = build_topic(topic_prefix, site_id, device_id, f"cmd/ublox/{command_type}/v1")
    return topic, message


def build_envelope(
    *,
    schema: str,
    seq: int,
    device_id: str,
    site_id: str,
    frontend: str,
    source: str,
    event_time: Any,
    ingest_time: Any,
    data: dict[str, Any],
    event_id_suffix: str = "",
) -> dict[str, Any]:
    if not schema:
        raise ValueError("schema must not be empty")
    if not device_id:
        raise ValueError("device_id must not be empty")
    if not site_id:
        raise ValueError("site_id must not be empty")
    if not source:
        raise ValueError("source must not be empty")
    if data is None:
        raise ValueError("data must not be None")

    return {
        "schema": schema,
        "event_id": build_event_id(device_id, seq, event_id_suffix),
        "seq": int(seq),
        "device_id": device_id,
        "site_id": site_id,
        "frontend": frontend,
        "source": source,
        "event_time": normalize_utc(event_time),
        "ingest_time": normalize_utc(ingest_time),
        "data": data,
    }


def build_raw_ublox_message(
    event: dict[str, Any],
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
) -> tuple[str, dict[str, Any]]:
    payload = _require_payload(event)
    receiver = str(payload.get("receiver") or "unknown")
    seq = int(event.get("seq", 0))
    ingest_time = payload.get("received_at_utc") or event.get("created_at_utc")
    data = {
        "receiver": receiver,
        "identity": payload.get("identity"),
        "tow_s": _to_float_or_none(payload.get("tow_s")),
        "raw_len": int(payload.get("raw_len", 0)),
        "raw_encoding": "base64",
        "raw_base64": payload.get("raw_base64"),
    }
    topic = build_topic(topic_prefix, site_id, device_id, "raw/ublox/v1")
    message = build_envelope(
        schema="gnss.raw.ublox.v1",
        seq=seq,
        device_id=device_id,
        site_id=site_id,
        frontend="ublox",
        source=receiver,
        event_time=ingest_time,
        ingest_time=ingest_time,
        data=data,
    )
    return topic, message


def build_raw_sdr_snapshot_chunk_message(
    event: dict[str, Any],
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
) -> tuple[str, dict[str, Any]]:
    payload = _require_payload(event)
    file_id = str(payload.get("file_id") or "")
    if not file_id:
        raise ValueError("SDR snapshot file_id must not be empty")

    chunk_index = _to_int(payload.get("chunk_index"))
    chunk_count = _to_int(payload.get("chunk_count"))
    if chunk_index < 0:
        raise ValueError("SDR snapshot chunk_index must be non-negative")
    if chunk_count <= 0:
        raise ValueError("SDR snapshot chunk_count must be positive")
    if chunk_index >= chunk_count:
        raise ValueError("SDR snapshot chunk_index must be less than chunk_count")

    seq = int(event.get("seq", payload.get("frame_idx", 0)))
    event_time = payload.get("detected_at_utc") or event.get("created_at_utc")
    ingest_time = payload.get("created_at_utc") or event_time
    data = {
        "record_type": "snapshot_chunk",
        "receiver": str(payload.get("receiver") or "sdr0"),
        "file_id": file_id,
        "sample_format": str(payload.get("sample_format") or "sc16_q11"),
        "center_freq_hz": _to_int(payload.get("center_freq_hz")),
        "sample_rate_hz": _to_int(payload.get("sample_rate_hz")),
        "gain_db": _to_float_or_none(payload.get("gain_db")),
        "bandwidth_hz": _to_int_or_none(payload.get("bandwidth_hz")),
        "band": payload.get("band"),
        "requested_pre_seconds": _to_float_or_none(payload.get("requested_pre_seconds")),
        "requested_post_seconds": _to_float_or_none(payload.get("requested_post_seconds")),
        "sample_count": _to_int(payload.get("sample_count")),
        "file_bytes": _to_int(payload.get("file_bytes")),
        "file_sha256": payload.get("file_sha256"),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "chunk_bytes": _to_int(payload.get("chunk_bytes")),
        "chunk_sha256": payload.get("chunk_sha256"),
        "payload_encoding": "base64",
        "chunk_base64": payload.get("chunk_base64"),
        "detection": {
            "class": payload.get("class"),
            "confidence": _to_float_or_none(payload.get("confidence")),
            "frame_idx": _to_int_or_none(payload.get("frame_idx")),
        },
    }
    topic = build_topic(topic_prefix, site_id, device_id, "raw/sdr/v1")
    message = build_envelope(
        schema="gnss.raw.sdr.v1",
        seq=seq,
        device_id=device_id,
        site_id=site_id,
        frontend="sdr",
        source=data["receiver"],
        event_time=event_time,
        ingest_time=ingest_time,
        data=data,
        event_id_suffix=f"sdr_raw_{file_id}_{chunk_index:06d}",
    )
    return topic, message


def build_detect_sdr_message(
    event: dict[str, Any],
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
) -> tuple[str, dict[str, Any]]:
    payload = _require_payload(event)
    file_id = payload.get("file_id")
    seq = int(event.get("seq", payload.get("frame_idx", 0)))
    event_time = payload.get("detected_at_utc") or event.get("created_at_utc")
    ingest_time = payload.get("created_at_utc") or event_time
    probs = payload.get("probs")
    if probs is not None:
        probs = [_to_float(value) for value in probs]

    data = {
        "detector_family": "sdr_ai",
        "threat_type": payload.get("threat_type") or "jamming",
        "jamming": bool(payload.get("jamming", True)),
        "spoofing": payload.get("spoofing"),
        "class": payload.get("class"),
        "confidence": _to_float_or_none(payload.get("confidence")),
        "probs": probs,
        "class_names": payload.get("class_names"),
        "frame_idx": _to_int_or_none(payload.get("frame_idx")),
        "receiver": str(payload.get("receiver") or "sdr0"),
        "center_freq_hz": _to_int(payload.get("center_freq_hz")),
        "sample_rate_hz": _to_int(payload.get("sample_rate_hz")),
        "gain_db": _to_float_or_none(payload.get("gain_db")),
        "bandwidth_hz": _to_int_or_none(payload.get("bandwidth_hz")),
        "image_encoding": payload.get("image_encoding") or "png_base64",
        "spectrum_image_base64": payload.get("spectrum_image_base64"),
        "snapshot_file_id": file_id,
        "snapshot_sample_format": payload.get("sample_format") or "sc16_q11",
        "snapshot_sample_count": _to_int_or_none(payload.get("sample_count")),
        "snapshot_file_bytes": _to_int_or_none(payload.get("file_bytes")),
        "snapshot_file_sha256": payload.get("file_sha256"),
        "snapshot_chunk_count": _to_int_or_none(payload.get("chunk_count")),
    }
    topic = build_topic(topic_prefix, site_id, device_id, "detect/sdr/v1")
    message = build_envelope(
        schema="gnss.detect.sdr.v1",
        seq=seq,
        device_id=device_id,
        site_id=site_id,
        frontend="sdr",
        source=data["receiver"],
        event_time=event_time,
        ingest_time=ingest_time,
        data=data,
        event_id_suffix=f"sdr_detect_{file_id or seq}",
    )
    return topic, message


def build_detect_ublox_message(
    event: dict[str, Any],
    realtime_outputs: dict[str, dict[str, Any]],
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
) -> tuple[str, dict[str, Any]]:
    payload = _require_payload(event)
    seq = int(event.get("seq", 0))
    ingest_time = payload.get("received_at_utc") or event.get("created_at_utc")
    data = {
        "time": _build_time(payload),
        "position": _build_position(payload.get("nav_1") or payload.get("nav_2")),
        "summary": _build_summary(payload, realtime_outputs),
        "signals": _build_signals(payload),
        "detectors": _build_detectors(realtime_outputs),
    }
    topic = build_topic(topic_prefix, site_id, device_id, "detect/ublox/v1")
    message = build_envelope(
        schema="gnss.detect.ublox.v1",
        seq=seq,
        device_id=device_id,
        site_id=site_id,
        frontend="ublox",
        source="rx_pair",
        event_time=ingest_time,
        ingest_time=ingest_time,
        data=data,
    )
    return topic, message


build_detect_epoch_message = build_detect_ublox_message


def build_position_state_message(
    detect_message: dict[str, Any],
    *,
    topic_prefix: str,
) -> tuple[str, dict[str, Any]]:
    data = detect_message["data"]
    position_data = {
        **data["position"],
        "sat_count": data["summary"]["sat_count"],
        "avg_cno_dbhz": data["summary"]["avg_cno_dbhz"],
    }
    topic = build_topic(
        topic_prefix,
        detect_message["site_id"],
        detect_message["device_id"],
        "state/position/v1",
    )
    message = {
        **detect_message,
        "schema": "gnss.state.position.v1",
        "event_id": build_event_id(detect_message["device_id"], detect_message["seq"], "position"),
        "source": "rx_pair",
        "data": position_data,
    }
    return topic, message


def build_health_message(
    stats: dict[str, Any],
    *,
    topic_prefix: str,
    site_id: str,
    device_id: str,
    seq: int,
    cpu_percent: float | None = None,
) -> tuple[str, dict[str, Any]]:
    status = "running"
    if _to_int(stats.get("ingress_dropped")) or _to_int(stats.get("detect_dropped")) or _to_int(stats.get("raw_dropped")):
        status = "degraded"
    data = {
        "status": status,
        "ingress_backlog": _to_int(stats.get("ingress_backlog")),
        "detect_backlog": _to_int(stats.get("detect_backlog")),
        "raw_backlog": _to_int(stats.get("raw_backlog")),
        "ingress_dropped": _to_int(stats.get("ingress_dropped")),
        "detect_dropped": _to_int(stats.get("detect_dropped")),
        "raw_dropped": _to_int(stats.get("raw_dropped")),
        "raw_emitted": _to_int(stats.get("raw_emitted")),
        "unknown_events": _to_int(stats.get("unknown_events")),
        "last_seq": _to_int(stats.get("last_seq")),
        "mqtt_raw_published": _to_int(stats.get("mqtt_raw_published")),
        "mqtt_raw_failed": _to_int(stats.get("mqtt_raw_failed")),
        "mqtt_raw_queue_dropped": _to_int(stats.get("mqtt_raw_queue_dropped")),
        "mqtt_detect_published": _to_int(stats.get("mqtt_detect_published")),
        "mqtt_detect_failed": _to_int(stats.get("mqtt_detect_failed")),
        "mqtt_position_published": _to_int(stats.get("mqtt_position_published")),
        "mqtt_position_failed": _to_int(stats.get("mqtt_position_failed")),
        "mqtt_health_published": _to_int(stats.get("mqtt_health_published")),
        "mqtt_health_failed": _to_int(stats.get("mqtt_health_failed")),
        "cpu_percent": _to_float_or_none(cpu_percent),
    }
    now = utc_now_z()
    topic = build_topic(topic_prefix, site_id, device_id, "health/v1")
    message = build_envelope(
        schema="gnss.health.v1",
        seq=seq,
        device_id=device_id,
        site_id=site_id,
        frontend="mixed",
        source="pipeline",
        event_time=now,
        ingest_time=now,
        data=data,
        event_id_suffix="health",
    )
    return topic, message


def _require_payload(event: dict[str, Any]) -> dict[str, Any]:
    if event is None:
        raise ValueError("event must not be None")
    payload = event.get("payload")
    if payload is None:
        raise ValueError("event payload must not be None")
    return payload


def _build_time(payload: dict[str, Any]) -> dict[str, Any]:
    rawx = payload.get("rawx_1") or payload.get("rawx_2")
    return {
        "tow_s": _to_float_or_none(payload.get("tow_s") or getattr(rawx, "rcvTow", None)),
        "gps_week": _to_int_or_none(getattr(rawx, "week", None)),
    }


def _build_position(nav: Any) -> dict[str, Any]:
    return {
        "lat_deg": _scale_lat_lon(_first_attr(nav, ("lat", "latDeg"))),
        "lon_deg": _scale_lat_lon(_first_attr(nav, ("lon", "lonDeg"))),
        "height_m": _scale_height(_first_attr(nav, ("height", "hMSL", "height_m"))),
        "fix_type": _map_fix_type(_first_attr(nav, ("fixType", "fix_type"))),
        "pdop": _scale_pdop(_first_attr(nav, ("pDOP", "pdop"))),
    }


def _build_summary(payload: dict[str, Any], realtime_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    signals = _build_signals(payload)
    detector_values = list(realtime_outputs.values())
    spoofing_values = [item.get("spoofing") for item in detector_values]
    if any(value is True for value in spoofing_values):
        spoofing: bool | None = True
        status = "spoofed"
    elif any(value is False for value in spoofing_values):
        spoofing = False
        status = "normal"
    else:
        spoofing = None
        status = "pending"

    cno_values = [signal["cno_dbhz"] for signal in signals if signal["cno_dbhz"] is not None]
    avg_cno = sum(cno_values) / len(cno_values) if cno_values else None
    return {
        "sat_count": len(signals),
        "avg_cno_dbhz": avg_cno,
        "spoofing": spoofing,
        "status": status,
    }


def _build_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[int | None, int | None, int | None], dict[str, Any]] = {}
    for receiver_id, rawx_key in (("rx1", "rawx_1"), ("rx2", "rawx_2")):
        rawx = payload.get(rawx_key)
        for sat in getattr(rawx, "satData", []) or []:
            gnss_id = _to_int_or_none(getattr(sat, "gnssId", None))
            svid = _to_int_or_none(getattr(sat, "svId", None))
            sig_id = _to_int_or_none(getattr(sat, "sigId", None))
            key = (gnss_id, svid, sig_id)
            item = merged.setdefault(
                key,
                {
                    "gnss": _gnss_name(gnss_id),
                    "svid": svid,
                    "signal": _signal_name(gnss_id, sig_id),
                    "prn": _format_prn(gnss_id, svid),
                    "_cno_values": [],
                    "used_in_fix": None,
                    "receiver_ids": [],
                },
            )
            cno = _to_float_or_none(getattr(sat, "cno", None))
            if cno is not None:
                item["_cno_values"].append(cno)
            if receiver_id not in item["receiver_ids"]:
                item["receiver_ids"].append(receiver_id)

    result = []
    for item in merged.values():
        cno_values = item.pop("_cno_values")
        item["cno_dbhz"] = sum(cno_values) / len(cno_values) if cno_values else None
        result.append(item)
    return sorted(result, key=lambda entry: (entry["gnss"], entry["svid"] or -1, entry["signal"] or ""))


def _build_detectors(realtime_outputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    detectors = {}
    for output_name, output in realtime_outputs.items():
        spoofing = output.get("spoofing")
        if spoofing is True:
            status = "spoofed"
        elif spoofing is False:
            status = "normal"
        else:
            status = "pending"
        detectors[output_name] = {
            "detector_name": output.get("detector_name"),
            "measurement_name": output.get("measurement_name"),
            "score": _to_float_or_none(output.get("score")),
            "threshold": _to_float_or_none(output.get("threshold")),
            "spoofing": spoofing if spoofing in (True, False, None) else None,
            "status": status,
            "reference_svid": _to_int_or_none(output.get("reference_svid")),
            "visible_svids": [_to_int(value) for value in output.get("visible_svids", [])],
            "suspect_svids": [_to_int(value) for value in output.get("suspect_svids", [])],
        }
    return detectors


def _first_attr(obj: Any, names: tuple[str, ...]) -> Any:
    if obj is None:
        return None
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _scale_lat_lon(value: Any) -> float | None:
    number = _to_float_or_none(value)
    if number is None:
        return None
    if abs(number) > 180:
        return number * 1e-7
    return number


def _scale_height(value: Any) -> float | None:
    number = _to_float_or_none(value)
    if number is None:
        return None
    if abs(number) > 10000:
        return number / 1000.0
    return number


def _scale_pdop(value: Any) -> float | None:
    number = _to_float_or_none(value)
    if number is None:
        return None
    if number > 100:
        return number / 100.0
    return number


def _map_fix_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return {
        0: "no_fix",
        1: "dead_reckoning",
        2: "2d",
        3: "3d",
        4: "gnss_dead_reckoning",
        5: "time_only",
    }.get(_to_int(value), "unknown")


def _gnss_name(gnss_id: int | None) -> str:
    return GNSS_NAMES.get(gnss_id, ("UNKNOWN", "U"))[0]


def _format_prn(gnss_id: int | None, svid: int | None) -> str:
    prefix = GNSS_NAMES.get(gnss_id, ("UNKNOWN", "U"))[1]
    if svid is None:
        return f"{prefix}00"
    return f"{prefix}{svid:02d}"


def _signal_name(gnss_id: int | None, sig_id: int | None) -> str | None:
    if gnss_id is None or sig_id is None:
        return None
    return SIGNAL_NAMES.get((gnss_id, sig_id), f"sig{sig_id}")


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float:
    converted = _to_float_or_none(value)
    return converted if converted is not None else 0.0


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    converted = _to_int_or_none(value)
    return converted if converted is not None else 0
