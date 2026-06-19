from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .base import SdrSourceSettings
from .utils import (
    call_usrp_config,
    complex64_to_sc16_q11_bytes,
    metadata_error_text,
    set_usrp_rx_freq,
    validate_positive,
)

LOGGER = logging.getLogger("sdr_sources.usrp")


class UhdUsrpReceiverSource:
    def __init__(
        self,
        settings: SdrSourceSettings,
        uhd_module: Any | None = None,
    ) -> None:
        validate_positive("SDR_SAMPLE_RATE", settings.sample_rate_hz)
        validate_positive("SDR_BANDWIDTH", settings.bandwidth_hz)
        if settings.usrp_channel < 0:
            raise ValueError("SDR_USRP_CHANNEL must be non-negative")
        if not settings.usrp_args:
            raise ValueError("SDR_USRP_ARGS must not be empty for USRP sources")

        if uhd_module is None:
            try:
                import uhd as uhd_module
            except ImportError as exc:
                raise RuntimeError(
                    "UHD Python module is required for SDR_SOURCE=usrp_x300. "
                    "Install UHD with Python API enabled on the RK3588 host."
                ) from exc

        self._settings = settings
        self._uhd = uhd_module
        self._channel = int(settings.usrp_channel)
        self._recv_timeout_s = float(settings.usrp_recv_timeout_s)
        validate_positive("SDR_USRP_RECV_TIMEOUT", self._recv_timeout_s)

        self._usrp = self._uhd.usrp.MultiUSRP(settings.usrp_args)
        call_usrp_config(self._usrp.set_rx_rate, settings.sample_rate_hz, self._channel)
        set_usrp_rx_freq(self._usrp, self._uhd, settings.center_freq_hz, self._channel)
        call_usrp_config(self._usrp.set_rx_gain, settings.gain_db, self._channel)
        if settings.usrp_set_bandwidth and hasattr(self._usrp, "set_rx_bandwidth"):
            call_usrp_config(self._usrp.set_rx_bandwidth, settings.bandwidth_hz, self._channel)
        elif hasattr(self._usrp, "set_rx_bandwidth"):
            LOGGER.info(
                "usrp_rx_bandwidth_not_set requested_bandwidth_hz=%s reason=SDR_USRP_SET_BANDWIDTH_false",
                settings.bandwidth_hz,
            )
        if settings.usrp_antenna:
            call_usrp_config(self._usrp.set_rx_antenna, settings.usrp_antenna, self._channel)

        stream_args = self._uhd.usrp.StreamArgs("fc32", "sc16")
        stream_args.channels = [self._channel]
        if settings.usrp_stream_args:
            stream_args.args = settings.usrp_stream_args
        self._rx_streamer = self._usrp.get_rx_stream(stream_args)
        self._metadata = self._uhd.types.RXMetadata()
        max_samps = int(self._rx_streamer.get_max_num_samps())
        if max_samps <= 0:
            raise RuntimeError("UHD RX streamer returned non-positive max samples")
        self._recv_buffer = np.zeros(max_samps, dtype=np.complex64)
        self._start_stream()
        LOGGER.info(
            "sdr_source_started source=usrp_x300 args=%s freq_hz=%s sample_rate_hz=%s gain_db=%s bandwidth_hz=%s channel=%s antenna=%s stream_args=%s",
            settings.usrp_args,
            settings.center_freq_hz,
            settings.sample_rate_hz,
            settings.gain_db,
            settings.bandwidth_hz,
            self._channel,
            settings.usrp_antenna or "<default>",
            settings.usrp_stream_args or "<default>",
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

            error_text = metadata_error_text(self._metadata)
            if error_text is not None:
                LOGGER.warning("usrp_rx_metadata_error error=%s", error_text)

            count = int(count)
            if count <= 0:
                continue
            samples[received : received + count] = view[:count]
            received += count

        return samples, complex64_to_sc16_q11_bytes(samples)

    def close(self) -> None:
        try:
            stream_cmd = self._uhd.types.StreamCMD(self._uhd.types.StreamMode.stop_cont)
            self._rx_streamer.issue_stream_cmd(stream_cmd)
        except Exception:
            LOGGER.exception("usrp_stop_stream_error")
