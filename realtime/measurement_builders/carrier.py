from __future__ import annotations

from realtime.measurement_builders.base import MeasurementBuilder
from realtime.measurement_builders.common import (
    choose_reference_svid,
    extract_gps_l1_observations,
    fractional_cycles,
)
from realtime.types import MeasurementFrame, RealtimeEpochPair


class CarrierMeasurementBuilder(MeasurementBuilder):
    """Builds fractional carrier-phase DD values for one realtime epoch."""

    measurement_name = "carrier"

    def build(self, epoch_pair: RealtimeEpochPair) -> MeasurementFrame | None:
        obs1 = extract_gps_l1_observations(epoch_pair.rawx_1)
        obs2 = extract_gps_l1_observations(epoch_pair.rawx_2)
        reference_svid = choose_reference_svid(obs1, obs2)
        if reference_svid is None:
            return None

        common_svids = sorted(set(obs1) & set(obs2))
        ref_sd = obs2[reference_svid].cp_cycles - obs1[reference_svid].cp_cycles
        dd_values: dict[int, float] = {}
        for svid in common_svids:
            if svid == reference_svid:
                continue
            carrier_sd = obs2[svid].cp_cycles - obs1[svid].cp_cycles
            dd_values[svid] = fractional_cycles(carrier_sd - ref_sd)

        return MeasurementFrame(
            measurement_name=self.measurement_name,
            tow_s=epoch_pair.tow_s,
            reference_svid=reference_svid,
            visible_svids=tuple(common_svids),
            dd_values=dd_values,
            metadata={"received_at_utc": epoch_pair.received_at_utc},
        )

