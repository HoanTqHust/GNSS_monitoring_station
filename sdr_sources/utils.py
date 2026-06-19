from __future__ import annotations

from typing import Any

import numpy as np


def validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def complex64_to_sc16_q11_bytes(samples: np.ndarray) -> bytes:
    if samples is None:
        raise ValueError("samples must not be None")
    complex_samples = np.asarray(samples, dtype=np.complex64)
    clipped_real = np.clip(np.real(complex_samples), -1.0, 1.0)
    clipped_imag = np.clip(np.imag(complex_samples), -1.0, 1.0)
    interleaved = np.empty(complex_samples.size * 2, dtype="<i2")
    interleaved[0::2] = np.rint(clipped_real * 2047.0).astype("<i2")
    interleaved[1::2] = np.rint(clipped_imag * 2047.0).astype("<i2")
    return interleaved.tobytes()


def metadata_error_text(metadata: Any) -> str | None:
    error_code = getattr(metadata, "error_code", None)
    if error_code is None:
        return None
    text = str(error_code).lower()
    if text in {"0", "none", "rxmetadataerrorcode.none", "rx_metadata_error_code.none"}:
        return None
    if text.endswith(".none") or text.endswith("_none"):
        return None
    return str(error_code)


def call_usrp_config(method: Any, value: Any, channel: int) -> None:
    try:
        method(value, channel)
    except TypeError:
        method(value)


def set_usrp_rx_freq(usrp: Any, uhd_module: Any, freq_hz: float, channel: int) -> None:
    tune_request_cls = getattr(getattr(uhd_module, "types", None), "TuneRequest", None)
    if tune_request_cls is None:
        call_usrp_config(usrp.set_rx_freq, freq_hz, channel)
        return
    tune_request = tune_request_cls(float(freq_hz))
    call_usrp_config(usrp.set_rx_freq, tune_request, channel)
