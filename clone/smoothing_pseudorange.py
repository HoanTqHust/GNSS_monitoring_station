#!/usr/bin/env python3
"""
Standalone batch builder for carrier-smoothed pseudorange double differences.

This script reads the repo's existing UBX logs, applies a Hatch filter per
satellite, and exports carrier-smoothed pseudorange DD traces without running
SoS or D3 detection.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SPEED_OF_LIGHT_MPS = 299792458.0
GPS_L1_HZ = 1575.42e6
GPS_L1_WAVELENGTH_M = SPEED_OF_LIGHT_MPS / GPS_L1_HZ
LOGGER = logging.getLogger("smoothing_pseudorange")


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
class SmoothedEpochRecord:
    epoch_index: int
    tow_s: float
    reference_svid: int
    visible_svids: tuple[int, ...]
    smoothed_code_dd_m: dict[int, float]


@dataclass(frozen=True)
class SmoothingConfig:
    hatch_window: int
    tow_tolerance_s: float
    skip_initial_epochs: int
    max_epochs_per_file: int | None


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s %(message)s")


def validate_config(config: SmoothingConfig) -> None:
    if config.hatch_window <= 0:
        raise ValueError("hatch_window must be positive.")
    if config.tow_tolerance_s < 0:
        raise ValueError("tow_tolerance_s must be non-negative.")
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


def choose_reference_svid(epoch_pairs: list[tuple[RAWXEpoch, RAWXEpoch]]) -> int:
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


def build_smoothed_records(
    epoch_pairs: list[tuple[RAWXEpoch, RAWXEpoch]],
    reference_svid: int,
    hatch_window: int,
) -> list[SmoothedEpochRecord]:
    records: list[SmoothedEpochRecord] = []
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

        if reference_svid not in states1 or reference_svid not in states2:
            continue

        smooth_ref_sd = states2[reference_svid].smoothed_pr_m - states1[reference_svid].smoothed_pr_m
        smoothed_code_dd_m: dict[int, float] = {}
        for svid in candidate_svids:
            if svid not in states1 or svid not in states2:
                continue
            smooth_sd = states2[svid].smoothed_pr_m - states1[svid].smoothed_pr_m
            smoothed_code_dd_m[svid] = smooth_sd - smooth_ref_sd

        records.append(
            SmoothedEpochRecord(
                epoch_index=epoch_index,
                tow_s=epoch1.tow_s,
                reference_svid=reference_svid,
                visible_svids=tuple(candidate_svids),
                smoothed_code_dd_m=smoothed_code_dd_m,
            )
        )
    return records


def flatten_smoothed_records(records: list[SmoothedEpochRecord]):
    import pandas as pd

    all_svids = sorted({svid for record in records for svid in record.smoothed_code_dd_m})
    columns = ["epoch_index", "tow_s", "reference_svid", "num_visible_svids", "mean_abs_dd_m"]
    columns.extend(f"svid_{svid:02d}_dd_m" for svid in all_svids)

    rows: list[dict[str, float | int]] = []
    for record in records:
        dd_values = list(record.smoothed_code_dd_m.values())
        row: dict[str, float | int] = {
            "epoch_index": record.epoch_index,
            "tow_s": record.tow_s,
            "reference_svid": record.reference_svid,
            "num_visible_svids": len(record.visible_svids),
            "mean_abs_dd_m": float(np.mean(np.abs(dd_values))) if dd_values else float("nan"),
        }
        for svid in all_svids:
            row[f"svid_{svid:02d}_dd_m"] = record.smoothed_code_dd_m.get(svid, float("nan"))
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def summarize_records(frame, scenario_name: str, reference_svid: int):
    import pandas as pd

    mean_abs_series = frame["mean_abs_dd_m"].dropna()
    return pd.DataFrame(
        [
            {
                "scenario": scenario_name,
                "epochs": int(len(frame)),
                "reference_svid": reference_svid,
                "mean_abs_dd_m": float(mean_abs_series.mean()) if len(mean_abs_series) else float("nan"),
                "max_abs_dd_m": float(mean_abs_series.max()) if len(mean_abs_series) else float("nan"),
            }
        ]
    )


def save_plots(frame, scenario_name: str, output_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        LOGGER.warning("scenario_empty_for_plot name=%s", scenario_name)
        return

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(
        frame["epoch_index"].to_numpy(dtype=float),
        frame["mean_abs_dd_m"].to_numpy(dtype=float),
        color="tab:blue",
        label="mean |smoothed DD|",
    )
    ax.set_xlabel("Matched epoch index")
    ax.set_ylabel("meters")
    ax.set_title(f"{scenario_name}: carrier-smoothed pseudorange DD")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"{scenario_name}_smoothed_dd.png", dpi=200)
    plt.close(fig)


def save_json(data: dict[str, object], output_path: Path) -> None:
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_scenario(
    scenario_name: str,
    file1: Path,
    file2: Path,
    config: SmoothingConfig,
) -> tuple[list[SmoothedEpochRecord], int]:
    LOGGER.info("scenario_start name=%s file1=%s file2=%s", scenario_name, file1, file2)
    epochs1 = read_rawx_epochs(file1, config.max_epochs_per_file)
    epochs2 = read_rawx_epochs(file2, config.max_epochs_per_file)
    matched_pairs = match_rawx_epochs(epochs1, epochs2, config.tow_tolerance_s)
    if not matched_pairs:
        raise ValueError(f"No matched RAWX epochs found for scenario '{scenario_name}'.")

    reference_svid = choose_reference_svid(matched_pairs)
    records = build_smoothed_records(matched_pairs, reference_svid, config.hatch_window)
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
        description="Standalone carrier-smoothed pseudorange DD batch builder."
    )
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory containing data/.")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory used to save outputs.")
    parser.add_argument("--hatch-window", type=int, default=30, help="Hatch filter window length in epochs.")
    parser.add_argument(
        "--tow-tolerance-ms",
        type=float,
        default=20.0,
        help="Maximum receiver TOW mismatch allowed when pairing epochs.",
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
        help="Read at most N RXM-RAWX epochs per file. Useful for smoke tests.",
    )
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    script_dir = Path(__file__).resolve().parent
    base_dir = Path(args.base_dir).resolve() if args.base_dir else resolve_base_path(script_dir)
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else script_dir / "output" / "smoothing_pseudorange"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    config = SmoothingConfig(
        hatch_window=args.hatch_window,
        tow_tolerance_s=args.tow_tolerance_ms / 1000.0,
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

    import pandas as pd

    summary_frames = []
    references: dict[str, int] = {}
    for scenario_name, (file1, file2) in scenario_files.items():
        records, reference_svid = run_scenario(scenario_name, file1, file2, config)
        references[scenario_name] = reference_svid
        frame = flatten_smoothed_records(records)
        frame.to_csv(output_root / f"{scenario_name}_smoothed_dd.csv", index=False)
        save_plots(frame, scenario_name, output_root / "plots")
        summary_frames.append(summarize_records(frame, scenario_name, reference_svid))

    summary_df = pd.concat(summary_frames, ignore_index=True)
    summary_df.to_csv(output_root / "smoothing_summary.csv", index=False)
    save_json(
        {
            "references": references,
            "config": {
                "hatch_window": config.hatch_window,
                "tow_tolerance_s": config.tow_tolerance_s,
                "skip_initial_epochs": config.skip_initial_epochs,
                "max_epochs_per_file": config.max_epochs_per_file,
            },
        },
        output_root / "smoothing_metadata.json",
    )
    print(summary_df.to_string(index=False))
    print(f"Saved outputs to: {output_root}")


if __name__ == "__main__":
    main()
