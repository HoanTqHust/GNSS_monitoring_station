from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GPS_L1_HZ = 1575.42e6
SPEED_OF_LIGHT_MPS = 299792458.0
GPS_L1_WAVELENGTH_M = SPEED_OF_LIGHT_MPS / GPS_L1_HZ


@dataclass(frozen=True)
class SatelliteObservation:
    pr_m: float
    cp_cycles: float
    locktime_ms: float | None


def extract_gps_l1_observations(rawx_data) -> dict[int, SatelliteObservation]:
    observations: dict[int, SatelliteObservation] = {}
    for sat in getattr(rawx_data, "satData", []):
        if sat.gnssId != 0 or sat.sigId != 0 or sat.svId is None:
            continue
        if sat.prMes is None or sat.cpMes is None:
            continue
        if np.isnan(sat.prMes) or np.isnan(sat.cpMes):
            continue
        observations[int(sat.svId)] = SatelliteObservation(
            pr_m=float(sat.prMes),
            cp_cycles=float(sat.cpMes),
            locktime_ms=float(sat.locktime) if getattr(sat, "locktime", None) is not None else None,
        )
    return observations


def choose_reference_svid(
    obs1: dict[int, SatelliteObservation], obs2: dict[int, SatelliteObservation]
) -> int | None:
    common_svids = sorted(set(obs1) & set(obs2))
    if not common_svids:
        return None
    return common_svids[0]


def fractional_cycles(value: float) -> float:
    return value - np.round(value)

