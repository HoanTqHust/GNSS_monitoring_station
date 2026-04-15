from __future__ import annotations

from dataclasses import dataclass

from realtime.measurement_builders.base import MeasurementBuilder
from realtime.measurement_builders.common import (
    GPS_L1_WAVELENGTH_M,
    choose_reference_svid,
    extract_gps_l1_observations,
)
from realtime.types import MeasurementFrame, RealtimeEpochPair


@dataclass
class HatchState:
    smoothed_pr_m: float
    prev_cp_m: float
    sample_count: int
    prev_locktime_ms: float | None


class SmoothedPseudorangeMeasurementBuilder(MeasurementBuilder):
    """Builds carrier-smoothed pseudorange DD values with per-satellite state."""

    measurement_name = "smoothed_pseudorange"

    def __init__(self, hatch_window: int = 30) -> None:
        self.hatch_window = hatch_window
        self._states_1: dict[int, HatchState] = {}
        self._states_2: dict[int, HatchState] = {}

    def build(self, epoch_pair: RealtimeEpochPair) -> MeasurementFrame | None:
        obs1 = extract_gps_l1_observations(epoch_pair.rawx_1)
        obs2 = extract_gps_l1_observations(epoch_pair.rawx_2)
        reference_svid = choose_reference_svid(obs1, obs2)
        if reference_svid is None:
            return None

        self._states_1 = self._prune_missing_states(self._states_1, set(obs1))
        self._states_2 = self._prune_missing_states(self._states_2, set(obs2))

        for svid, observation in obs1.items():
            self._states_1[svid] = self._update_hatch_state(self._states_1.get(svid), observation)
        for svid, observation in obs2.items():
            self._states_2[svid] = self._update_hatch_state(self._states_2.get(svid), observation)

        if reference_svid not in self._states_1 or reference_svid not in self._states_2:
            return None

        common_svids = sorted(set(obs1) & set(obs2))
        smooth_ref_sd = (
            self._states_2[reference_svid].smoothed_pr_m
            - self._states_1[reference_svid].smoothed_pr_m
        )

        dd_values: dict[int, float] = {}
        for svid in common_svids:
            if svid == reference_svid:
                continue
            if svid not in self._states_1 or svid not in self._states_2:
                continue
            smooth_sd = self._states_2[svid].smoothed_pr_m - self._states_1[svid].smoothed_pr_m
            dd_values[svid] = smooth_sd - smooth_ref_sd

        return MeasurementFrame(
            measurement_name=self.measurement_name,
            tow_s=epoch_pair.tow_s,
            reference_svid=reference_svid,
            visible_svids=tuple(common_svids),
            dd_values=dd_values,
            metadata={
                "received_at_utc": epoch_pair.received_at_utc,
                "hatch_window": self.hatch_window,
            },
        )

    def _update_hatch_state(self, state: HatchState | None, observation) -> HatchState:
        cp_m = observation.cp_cycles * GPS_L1_WAVELENGTH_M

        if state is None:
            return HatchState(
                smoothed_pr_m=observation.pr_m,
                prev_cp_m=cp_m,
                sample_count=1,
                prev_locktime_ms=observation.locktime_ms,
            )

        lock_reset = (
            observation.locktime_ms is not None
            and state.prev_locktime_ms is not None
            and observation.locktime_ms < state.prev_locktime_ms
        )
        if lock_reset:
            return HatchState(
                smoothed_pr_m=observation.pr_m,
                prev_cp_m=cp_m,
                sample_count=1,
                prev_locktime_ms=observation.locktime_ms,
            )

        sample_count = min(state.sample_count + 1, self.hatch_window)
        smoothed_pr_m = (observation.pr_m / sample_count) + ((sample_count - 1) / sample_count) * (
            state.smoothed_pr_m + (cp_m - state.prev_cp_m)
        )
        return HatchState(
            smoothed_pr_m=smoothed_pr_m,
            prev_cp_m=cp_m,
            sample_count=sample_count,
            prev_locktime_ms=observation.locktime_ms,
        )

    @staticmethod
    def _prune_missing_states(
        states: dict[int, HatchState], visible_svids: set[int]
    ) -> dict[int, HatchState]:
        return {svid: state for svid, state in states.items() if svid in visible_svids}

