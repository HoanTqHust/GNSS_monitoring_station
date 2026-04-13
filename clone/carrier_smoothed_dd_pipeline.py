#!/usr/bin/env python3
"""
Batch detector for the carrier-smoothed double-difference spoofing paper.

This script reuses the same UBX datasets already present in the repo:
- data/Non-SP/*.ubx
- data/SP/*.ubx

It computes three measurement families from RXM-RAWX observations:
- raw pseudorange DD
- fractional carrier-phase DD
- carrier-smoothed pseudorange DD (Hatch filter)

On top of those measurements it evaluates two simple detectors:
- SoS: mean squared DD per epoch
- D3: cluster-of-similar-DD heuristic per epoch

The current repo datasets appear to represent clean-vs-spoofed scenarios rather than
the mixed-tracking dataset used in the 2025 paper, so this script is suitable for
batch experimentation but not for full paper reproduction.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np

SPEED_OF_LIGHT_MPS = 299792458.0
GPS_L1_HZ = 1575.42e6
GPS_L1_WAVELENGTH_M = SPEED_OF_LIGHT_MPS / GPS_L1_HZ
LOGGER = logging.getLogger("carrier_smoothed_dd")


@dataclass(frozen=True)
class SatelliteObservation:
    pr_m: float
    cp_cycles: float
    locktime_ms: float | None


@dataclass(frozen=True)
class RAWXEpoch:
    tow_s: float
    observations: dict[int, SatelliteObservation]


@dataclass
class HatchState:
    smoothed_pr_m: float
    prev_cp_m: float
    sample_count: int
    prev_locktime_ms: float | None


@dataclass(frozen=True)
class EpochRecord:
    epoch_index: int
    tow_s: float
    visible_svids: tuple[int, ...]
    raw_code_dd_m: dict[int, float]
    carrier_frac_dd_cycles: dict[int, float]
    smoothed_code_dd_m: dict[int, float]


@dataclass(frozen=True)
class DetectorConfig:
    hatch_window: int
    tow_tolerance_s: float
    sos_clean_quantile: float
    d3_clean_quantile: float
    min_cluster_size: int
    skip_initial_epochs: int
    max_epochs_per_file: int | None


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s %(message)s",
    )


def validate_config(config: DetectorConfig) -> None:
    if config.hatch_window <= 0:
        raise ValueError("hatch_window must be positive.")
    if config.tow_tolerance_s < 0:
        raise ValueError("tow_tolerance_s must be non-negative.")
    if not 0.0 <= config.sos_clean_quantile <= 1.0:
        raise ValueError("sos_clean_quantile must be in [0, 1].")
    if not 0.0 <= config.d3_clean_quantile <= 1.0:
        raise ValueError("d3_clean_quantile must be in [0, 1].")
    if config.min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least 2.")
    if config.skip_initial_epochs < 0:
        raise ValueError("skip_initial_epochs must be non-negative.")
    if config.max_epochs_per_file is not None and config.max_epochs_per_file <= 0:
        raise ValueError("max_epochs_per_file must be positive when provided.")


def resolve_base_path(start_dir: Path) -> Path:
    candidates = [start_dir.resolve(), start_dir.resolve().parent]
    for base in candidates:
        if (base / "data" / "Non-SP" / "raw_data_1.ubx").exists():
            return base
    raise FileNotFoundError(
        "Cannot find data files. Expected data/Non-SP/raw_data_1.ubx under the script dir or parent."
    )


def read_rawx_epochs(file_path: Path, max_epochs: int | None = None) -> list[RAWXEpoch]:
    if not file_path.exists():
        raise FileNotFoundError(f"UBX file not found: {file_path}")

    try:
        from pyubx2 import UBXReader
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pyubx2 is required to read UBX files. Install clone/requirements.txt first."
        ) from exc

    epochs: list[RAWXEpoch] = []
    with file_path.open("rb") as stream:
        reader = UBXReader(stream, protfilter=2)
        for _, parsed in reader:
            if parsed.identity != "RXM-RAWX":
                continue

            observations: dict[int, SatelliteObservation] = {}
            for i in range(1, int(parsed.numMeas) + 1):
                gnss_id = getattr(parsed, f"gnssId_{i:02}", None)
                sig_id = getattr(parsed, f"sigId_{i:02}", None)
                svid = getattr(parsed, f"svId_{i:02}", None)
                pr_mes = getattr(parsed, f"prMes_{i:02}", None)
                cp_mes = getattr(parsed, f"cpMes_{i:02}", None)
                locktime = getattr(parsed, f"locktime_{i:02}", None)

                if gnss_id != 0 or sig_id != 0 or svid is None:
                    continue
                if pr_mes is None or cp_mes is None:
                    continue
                if np.isnan(pr_mes) or np.isnan(cp_mes):
                    continue

                observations[int(svid)] = SatelliteObservation(
                    pr_m=float(pr_mes),
                    cp_cycles=float(cp_mes),
                    locktime_ms=float(locktime) if locktime is not None else None,
                )

            if observations:
                epochs.append(RAWXEpoch(tow_s=float(parsed.rcvTow), observations=observations))
                if max_epochs is not None and len(epochs) >= max_epochs:
                    break

    return epochs


def match_rawx_epochs(
    epochs1: list[RAWXEpoch], epochs2: list[RAWXEpoch], tolerance_s: float
) -> list[tuple[RAWXEpoch, RAWXEpoch]]:
    pairs: list[tuple[RAWXEpoch, RAWXEpoch]] = []
    i = 0
    j = 0
    while i < len(epochs1) and j < len(epochs2):
        tow1 = epochs1[i].tow_s
        tow2 = epochs2[j].tow_s
        diff = tow1 - tow2

        if abs(diff) <= tolerance_s:
            pairs.append((epochs1[i], epochs2[j]))
            i += 1
            j += 1
        elif diff < 0:
            i += 1
        else:
            j += 1
    return pairs


def choose_reference_svid(epoch_pairs: Iterable[tuple[RAWXEpoch, RAWXEpoch]]) -> int:
    counts: dict[int, int] = {}
    for epoch1, epoch2 in epoch_pairs:
        common = set(epoch1.observations) & set(epoch2.observations)
        for svid in common:
            counts[svid] = counts.get(svid, 0) + 1

    if not counts:
        raise ValueError("No common GPS L1 satellites found across the matched epochs.")

    return max(counts.items(), key=lambda item: (item[1], -item[0]))[0]


def update_hatch_state(
    state: HatchState | None,
    observation: SatelliteObservation,
    window_size: int,
    wavelength_m: float = GPS_L1_WAVELENGTH_M,
) -> HatchState:
    cp_m = observation.cp_cycles * wavelength_m

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

    n = min(state.sample_count + 1, window_size)
    smoothed_pr_m = (observation.pr_m / n) + ((n - 1) / n) * (
        state.smoothed_pr_m + (cp_m - state.prev_cp_m)
    )
    return HatchState(
        smoothed_pr_m=smoothed_pr_m,
        prev_cp_m=cp_m,
        sample_count=n,
        prev_locktime_ms=observation.locktime_ms,
    )


def prune_missing_states(
    states: dict[int, HatchState], visible_svids: set[int]
) -> dict[int, HatchState]:
    return {svid: state for svid, state in states.items() if svid in visible_svids}


def fractional_cycles(value: float) -> float:
    return value - np.round(value)


def build_epoch_records(
    epoch_pairs: list[tuple[RAWXEpoch, RAWXEpoch]],
    reference_svid: int,
    hatch_window: int,
) -> list[EpochRecord]:
    records: list[EpochRecord] = []
    states1: dict[int, HatchState] = {}
    states2: dict[int, HatchState] = {}

    for epoch_index, (epoch1, epoch2) in enumerate(epoch_pairs):
        states1 = prune_missing_states(states1, set(epoch1.observations))
        states2 = prune_missing_states(states2, set(epoch2.observations))

        for svid, observation in epoch1.observations.items():
            states1[svid] = update_hatch_state(states1.get(svid), observation, hatch_window)
        for svid, observation in epoch2.observations.items():
            states2[svid] = update_hatch_state(states2.get(svid), observation, hatch_window)

        common_svids = sorted(set(epoch1.observations) & set(epoch2.observations))
        if reference_svid not in common_svids:
            continue

        candidate_svids = [svid for svid in common_svids if svid != reference_svid]
        if not candidate_svids:
            continue

        ref_obs1 = epoch1.observations[reference_svid]
        ref_obs2 = epoch2.observations[reference_svid]
        raw_ref_sd = ref_obs2.pr_m - ref_obs1.pr_m
        carr_ref_sd = ref_obs2.cp_cycles - ref_obs1.cp_cycles

        raw_code_dd_m: dict[int, float] = {}
        carrier_frac_dd_cycles: dict[int, float] = {}
        smoothed_code_dd_m: dict[int, float] = {}

        ref_smoothed_ready = reference_svid in states1 and reference_svid in states2
        if ref_smoothed_ready:
            smooth_ref_sd = (
                states2[reference_svid].smoothed_pr_m - states1[reference_svid].smoothed_pr_m
            )
        else:
            smooth_ref_sd = None

        for svid in candidate_svids:
            obs1 = epoch1.observations[svid]
            obs2 = epoch2.observations[svid]

            raw_code_dd_m[svid] = (obs2.pr_m - obs1.pr_m) - raw_ref_sd

            carrier_dd = (obs2.cp_cycles - obs1.cp_cycles) - carr_ref_sd
            carrier_frac_dd_cycles[svid] = fractional_cycles(carrier_dd)

            if smooth_ref_sd is not None and svid in states1 and svid in states2:
                smooth_sd = states2[svid].smoothed_pr_m - states1[svid].smoothed_pr_m
                smoothed_code_dd_m[svid] = smooth_sd - smooth_ref_sd

        records.append(
            EpochRecord(
                epoch_index=epoch_index,
                tow_s=epoch1.tow_s,
                visible_svids=tuple(candidate_svids),
                raw_code_dd_m=raw_code_dd_m,
                carrier_frac_dd_cycles=carrier_frac_dd_cycles,
                smoothed_code_dd_m=smoothed_code_dd_m,
            )
        )

    return records


def compute_sos(dd_by_svid: dict[int, float]) -> float:
    if not dd_by_svid:
        return float("nan")
    values = np.asarray(list(dd_by_svid.values()), dtype=float)
    return float(np.mean(np.square(values)))


def detect_d3_spoofed_svids(
    dd_by_svid: dict[int, float], abs_threshold: float, min_cluster_size: int
) -> list[int]:
    if len(dd_by_svid) < min_cluster_size:
        return []

    suspects: set[int] = set()
    items = list(dd_by_svid.items())
    for svid, value in items:
        cluster = {svid}
        for other_svid, other_value in items:
            if other_svid == svid:
                continue
            if abs(value - other_value) <= abs_threshold:
                cluster.add(other_svid)
        if len(cluster) >= min_cluster_size:
            suspects.update(cluster)
    return sorted(suspects)


def iter_pairwise_abs_diffs(records: Iterable[EpochRecord], measurement_name: str) -> list[float]:
    diffs: list[float] = []
    for record in records:
        dd_by_svid = getattr(record, measurement_name)
        values = list(dd_by_svid.values())
        for left, right in combinations(values, 2):
            diffs.append(abs(left - right))
    return diffs


def estimate_sos_threshold(records: list[EpochRecord], measurement_name: str, quantile: float) -> float:
    values = [
        compute_sos(getattr(record, measurement_name))
        for record in records
        if getattr(record, measurement_name)
    ]
    if not values:
        return float("nan")
    return float(np.quantile(np.asarray(values, dtype=float), quantile))


def estimate_d3_threshold(records: list[EpochRecord], measurement_name: str, quantile: float) -> float:
    diffs = iter_pairwise_abs_diffs(records, measurement_name)
    if not diffs:
        return float("nan")
    return float(np.quantile(np.asarray(diffs, dtype=float), quantile))


def measurement_specs() -> list[tuple[str, str]]:
    return [
        ("raw_code_dd_m", "raw_code"),
        ("carrier_frac_dd_cycles", "carrier_frac"),
        ("smoothed_code_dd_m", "smoothed_code"),
    ]


def build_detector_frame(
    records: list[EpochRecord],
    sos_thresholds: dict[str, float],
    d3_thresholds: dict[str, float],
    min_cluster_size: int,
):
    import pandas as pd

    columns = ["epoch_index", "tow_s", "num_visible_svids"]
    for _, measurement_slug in measurement_specs():
        columns.extend(
            [
                f"{measurement_slug}_sos",
                f"{measurement_slug}_sos_spoof",
                f"{measurement_slug}_d3_suspect_count",
                f"{measurement_slug}_d3_suspects",
            ]
        )

    rows: list[dict[str, object]] = []
    for record in records:
        row: dict[str, object] = {
            "epoch_index": record.epoch_index,
            "tow_s": record.tow_s,
            "num_visible_svids": len(record.visible_svids),
        }
        for measurement_attr, measurement_slug in measurement_specs():
            dd_by_svid = getattr(record, measurement_attr)
            sos_value = compute_sos(dd_by_svid)
            d3_threshold = d3_thresholds[measurement_slug]
            suspects = (
                detect_d3_spoofed_svids(dd_by_svid, d3_threshold, min_cluster_size)
                if dd_by_svid and not np.isnan(d3_threshold)
                else []
            )

            row[f"{measurement_slug}_sos"] = sos_value
            row[f"{measurement_slug}_sos_spoof"] = (
                bool(sos_value < sos_thresholds[measurement_slug])
                if not np.isnan(sos_value) and not np.isnan(sos_thresholds[measurement_slug])
                else False
            )
            row[f"{measurement_slug}_d3_suspect_count"] = len(suspects)
            row[f"{measurement_slug}_d3_suspects"] = ",".join(str(svid) for svid in suspects)
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def summarize_detector_frame(frame, scenario_name: str):
    import pandas as pd

    rows: list[dict[str, object]] = []
    for _, measurement_slug in measurement_specs():
        sos_col = f"{measurement_slug}_sos_spoof"
        d3_col = f"{measurement_slug}_d3_suspect_count"
        rows.append(
            {
                "scenario": scenario_name,
                "measurement": measurement_slug,
                "epochs": int(len(frame)),
                "sos_spoof_fraction": float(frame[sos_col].mean()) if len(frame) else float("nan"),
                "d3_any_suspect_fraction": (
                    float((frame[d3_col] > 0).mean()) if len(frame) else float("nan")
                ),
                "d3_mean_suspect_count": float(frame[d3_col].mean()) if len(frame) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def save_json(data: dict[str, object], output_path: Path) -> None:
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_detector_plots(
    frame,
    scenario_name: str,
    sos_thresholds: dict[str, float],
    output_dir: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        LOGGER.warning("scenario_empty_for_plot name=%s", scenario_name)
        return

    x = frame["epoch_index"].to_numpy(dtype=float)

    for _, measurement_slug in measurement_specs():
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        sos_col = f"{measurement_slug}_sos"
        axes[0].plot(x, frame[sos_col].to_numpy(dtype=float), label=f"{measurement_slug} SoS")
        if not np.isnan(sos_thresholds[measurement_slug]):
            axes[0].axhline(
                sos_thresholds[measurement_slug],
                color="red",
                linestyle="--",
                label="clean-derived threshold",
            )
        axes[0].set_ylabel("SoS")
        axes[0].set_title(f"{scenario_name}: {measurement_slug} detector traces")
        axes[0].grid(True)
        axes[0].legend()

        d3_col = f"{measurement_slug}_d3_suspect_count"
        axes[1].plot(
            x,
            frame[d3_col].to_numpy(dtype=float),
            label=f"{measurement_slug} D3 suspect count",
            color="tab:orange",
        )
        axes[1].set_xlabel("Matched epoch index")
        axes[1].set_ylabel("suspect satellites")
        axes[1].grid(True)
        axes[1].legend()

        fig.tight_layout()
        fig.savefig(output_dir / f"{scenario_name}_{measurement_slug}_detectors.png", dpi=200)
        plt.close(fig)


def run_scenario(
    scenario_name: str,
    file1: Path,
    file2: Path,
    config: DetectorConfig,
) -> tuple[list[EpochRecord], int]:
    LOGGER.info(
        "scenario_start name=%s file1=%s file2=%s",
        scenario_name,
        file1,
        file2,
    )
    epochs1 = read_rawx_epochs(file1, config.max_epochs_per_file)
    epochs2 = read_rawx_epochs(file2, config.max_epochs_per_file)
    matched_pairs = match_rawx_epochs(epochs1, epochs2, config.tow_tolerance_s)
    if not matched_pairs:
        raise ValueError(f"No matched RAWX epochs found for scenario '{scenario_name}'.")

    reference_svid = choose_reference_svid(matched_pairs)
    records = build_epoch_records(matched_pairs, reference_svid, config.hatch_window)
    if config.skip_initial_epochs:
        records = records[config.skip_initial_epochs :]

    LOGGER.info(
        "scenario_done name=%s epochs_rx1=%d epochs_rx2=%d matched_epochs=%d records=%d reference_svid=%d skipped_initial=%d",
        scenario_name,
        len(epochs1),
        len(epochs2),
        len(matched_pairs),
        len(records),
        reference_svid,
        config.skip_initial_epochs,
    )
    return records, reference_svid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch detector for carrier-smoothed pseudorange double-difference experiments."
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Base directory containing data/Non-SP and data/SP.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory used to save CSV, JSON and plots.",
    )
    parser.add_argument(
        "--hatch-window",
        type=int,
        default=30,
        help="Hatch filter window length in epochs.",
    )
    parser.add_argument(
        "--tow-tolerance-ms",
        type=float,
        default=20.0,
        help="Maximum receiver TOW mismatch allowed when pairing epochs.",
    )
    parser.add_argument(
        "--sos-clean-quantile",
        type=float,
        default=0.05,
        help="Lower clean-data quantile used as the SoS spoofing threshold.",
    )
    parser.add_argument(
        "--d3-clean-quantile",
        type=float,
        default=0.05,
        help="Lower clean-data quantile used as the D3 similarity threshold.",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=3,
        help="Minimum number of satellites required to form a D3 spoof cluster.",
    )
    parser.add_argument(
        "--skip-initial-epochs",
        type=int,
        default=5,
        help="Discard the first N matched epochs to let the Hatch filter stabilize.",
    )
    parser.add_argument(
        "--max-epochs-per-file",
        type=int,
        default=None,
        help="Read at most N RXM-RAWX epochs per file. Useful for fast batch smoke tests.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level, for example INFO or DEBUG.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    script_dir = Path(__file__).resolve().parent
    base_dir = Path(args.base_dir).resolve() if args.base_dir else resolve_base_path(script_dir)
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else script_dir / "output" / "carrier_smoothed_dd"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    config = DetectorConfig(
        hatch_window=args.hatch_window,
        tow_tolerance_s=args.tow_tolerance_ms / 1000.0,
        sos_clean_quantile=args.sos_clean_quantile,
        d3_clean_quantile=args.d3_clean_quantile,
        min_cluster_size=args.min_cluster_size,
        skip_initial_epochs=args.skip_initial_epochs,
        max_epochs_per_file=args.max_epochs_per_file,
    )
    validate_config(config)

    scenario_files = {
        "non_sp": (
            base_dir / "data" / "Non-SP" / "raw_data_1.ubx",
            base_dir / "data" / "Non-SP" / "raw_data_2.ubx",
        ),
        "sp": (
            base_dir / "data" / "SP" / "raw_data_1.ubx",
            base_dir / "data" / "SP" / "raw_data_2.ubx",
        ),
    }

    scenario_records: dict[str, list[EpochRecord]] = {}
    reference_svids: dict[str, int] = {}
    for scenario_name, (file1, file2) in scenario_files.items():
        records, reference_svid = run_scenario(scenario_name, file1, file2, config)
        scenario_records[scenario_name] = records
        reference_svids[scenario_name] = reference_svid

    clean_records = scenario_records["non_sp"]
    sos_thresholds = {
        measurement_slug: estimate_sos_threshold(clean_records, measurement_attr, config.sos_clean_quantile)
        for measurement_attr, measurement_slug in measurement_specs()
    }
    d3_thresholds = {
        measurement_slug: estimate_d3_threshold(clean_records, measurement_attr, config.d3_clean_quantile)
        for measurement_attr, measurement_slug in measurement_specs()
    }

    threshold_payload = {
        "reference_svids": reference_svids,
        "sos_thresholds": sos_thresholds,
        "d3_thresholds": d3_thresholds,
        "config": {
            "hatch_window": config.hatch_window,
            "tow_tolerance_s": config.tow_tolerance_s,
            "sos_clean_quantile": config.sos_clean_quantile,
            "d3_clean_quantile": config.d3_clean_quantile,
            "min_cluster_size": config.min_cluster_size,
            "skip_initial_epochs": config.skip_initial_epochs,
            "max_epochs_per_file": config.max_epochs_per_file,
        },
    }
    save_json(threshold_payload, output_root / "detector_thresholds.json")

    import pandas as pd

    summary_frames = []
    for scenario_name, records in scenario_records.items():
        frame = build_detector_frame(records, sos_thresholds, d3_thresholds, config.min_cluster_size)
        frame.to_csv(output_root / f"{scenario_name}_detectors.csv", index=False)
        save_detector_plots(frame, scenario_name, sos_thresholds, output_root / "plots")
        summary_frames.append(summarize_detector_frame(frame, scenario_name))

    summary_df = pd.concat(summary_frames, ignore_index=True)
    summary_df.to_csv(output_root / "detector_summary.csv", index=False)
    print(summary_df.to_string(index=False))
    print(f"Saved outputs to: {output_root}")


if __name__ == "__main__":
    main()
