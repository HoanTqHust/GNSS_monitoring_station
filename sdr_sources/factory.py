from __future__ import annotations

from typing import Any

from .base import SdrReceiverSource, SdrSourceSettings
from .bladerf_source import BladeRfReceiverSource
from .usrp_source import UhdUsrpReceiverSource


def sdr_source_settings_from_config(config_obj: Any) -> SdrSourceSettings:
    return SdrSourceSettings(
        sample_rate_hz=float(config_obj.SDR_SAMPLE_RATE),
        center_freq_hz=float(config_obj.SDR_FREQ),
        gain_db=float(config_obj.SDR_GAIN),
        bandwidth_hz=float(config_obj.SDR_BANDWIDTH),
        bladerf_device=str(config_obj.SDR_DEVICE),
        usrp_args=str(config_obj.SDR_USRP_ARGS),
        usrp_channel=int(config_obj.SDR_USRP_CHANNEL),
        usrp_antenna=str(config_obj.SDR_USRP_ANTENNA),
        usrp_stream_args=str(config_obj.SDR_USRP_STREAM_ARGS),
        usrp_recv_timeout_s=float(config_obj.SDR_USRP_RECV_TIMEOUT),
        usrp_set_bandwidth=bool(config_obj.SDR_USRP_SET_BANDWIDTH),
    )


def open_sdr_receiver_source(
    source_name: str,
    settings: SdrSourceSettings,
    *,
    uhd_module: Any | None = None,
) -> SdrReceiverSource:
    source = str(source_name).strip().lower()
    if source in {"usrp_x300", "usrp", "x300"}:
        return UhdUsrpReceiverSource(settings=settings, uhd_module=uhd_module)
    if source in {"bladerf", "blade_rf"}:
        return BladeRfReceiverSource(settings=settings)
    raise ValueError(f"Unsupported SDR_SOURCE: {source_name}")
