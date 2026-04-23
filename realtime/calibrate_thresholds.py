from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from pyubx2 import UBXReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.RAWXData import RAWXData
from realtime.measurement_builders import (  # noqa: E402
    CarrierMeasurementBuilder,
    SmoothedPseudorangeMeasurementBuilder,
)
from realtime.types import MeasurementFrame, RealtimeEpochPair  # noqa: E402

LOGGER = logging.getLogger("realtime.calibrate_thresholds")


@dataclass(frozen=True)
class CalibrationConfig:
    file1: str
    file2: str
    output_path: str
    tow_tolerance_s: float
    sos_clean_quantile: float
    d3_clean_quantile: float
    skip_initial_epochs: int
    hatch_window: int
    min_cluster_size: int
    max_epochs_per_file: int | None


@dataclass(frozen=True)
class CalibrationResult:
    sos_carrier: float
    sos_smoothed_pseudorange: float
    d3_carrier: float
    d3_smoothed_pseudorange: float


@dataclass(frozen=True)
class RawxEpochRecord:
    tow_s: float
    rawx: RAWXData
    nav: object | None


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s %(message)s")


def validate_config(config: CalibrationConfig) -> None:
    if config.tow_tolerance_s < 0:
        raise ValueError("tow_tolerance_s must be non-negative.")
    if not 0.0 <= config.sos_clean_quantile <= 1.0:
        raise ValueError("sos_clean_quantile must be in [0, 1].")
    if not 0.0 <= config.d3_clean_quantile <= 1.0:
        raise ValueError("d3_clean_quantile must be in [0, 1].")
    if config.skip_initial_epochs < 0:
        raise ValueError("skip_initial_epochs must be non-negative.")
    if config.hatch_window <= 0:
        raise ValueError("hatch_window must be positive.")
    if config.min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least 2.")
    if config.max_epochs_per_file is not None and config.max_epochs_per_file <= 0:
        raise ValueError("max_epochs_per_file must be positive when provided.")


def read_rawx_epochs(file_path: Path, max_epochs: int | None = None) -> list[RawxEpochRecord]:
    if not file_path.exists():
        raise FileNotFoundError(f"UBX file not found: {file_path}")

    epochs: list[RawxEpochRecord] = []
    pending_rawx: RAWXData | None = None
    pending_nav: object | None = None
    with file_path.open("rb") as stream:
        reader = UBXReader(stream, protfilter=2)
        for _, parsed in reader:
            if parsed.identity == "RXM-RAWX":
                pending_rawx = RAWXData(parsed)
            elif parsed.identity == "NAV-PVT":
                pending_nav = parsed

            if pending_rawx is not None and pending_nav is not None:
                epochs.append(
                    RawxEpochRecord(
                        tow_s=float(pending_rawx.rcvTow),
                        rawx=pending_rawx,
                        nav=pending_nav,
                    )
                )
                pending_rawx = None
                pending_nav = None
                if max_epochs is not None and len(epochs) >= max_epochs:
                    break
    return epochs


def match_epochs(
    epochs1: list[RawxEpochRecord], epochs2: list[RawxEpochRecord], tolerance_s: float
) -> list[RealtimeEpochPair]:
    pairs: list[RealtimeEpochPair] = []
    index1 = 0
    index2 = 0
    while index1 < len(epochs1) and index2 < len(epochs2):
        tow1 = epochs1[index1].tow_s
        tow2 = epochs2[index2].tow_s
        diff = tow1 - tow2

        if abs(diff) <= tolerance_s:
            pairs.append(
                RealtimeEpochPair(
                    tow_s=min(tow1, tow2),
                    rawx_1=epochs1[index1].rawx,
                    nav_1=epochs1[index1].nav,
                    rawx_2=epochs2[index2].rawx,
                    nav_2=epochs2[index2].nav,
                )
            )
            index1 += 1
            index2 += 1
        elif diff < 0:
            index1 += 1
        else:
            index2 += 1
    return pairs


def build_measurement_frames(
    epoch_pairs: list[RealtimeEpochPair],
    hatch_window: int,
    skip_initial_epochs: int,
) -> dict[str, list[MeasurementFrame]]:
    builders = {
        "carrier": CarrierMeasurementBuilder(),
        "smoothed_pseudorange": SmoothedPseudorangeMeasurementBuilder(hatch_window=hatch_window),
    }
    frames_by_measurement: dict[str, list[MeasurementFrame]] = {key: [] for key in builders}

    for epoch_pair in epoch_pairs:
        for measurement_name, builder in builders.items():
            frame = builder.build(epoch_pair)
            if frame is not None:
                frames_by_measurement[measurement_name].append(frame)

    if skip_initial_epochs:
        if len(frames_by_measurement["carrier"]) > skip_initial_epochs:
            frames_by_measurement["carrier"] = frames_by_measurement["carrier"][skip_initial_epochs:]
        if len(frames_by_measurement["smoothed_pseudorange"]) > skip_initial_epochs:
            frames_by_measurement["smoothed_pseudorange"] = frames_by_measurement[
                "smoothed_pseudorange"
            ][skip_initial_epochs:]
    return frames_by_measurement


def compute_sos_score(frame: MeasurementFrame) -> float | None:
    if not frame.dd_values:
        return None
    values = np.asarray(list(frame.dd_values.values()), dtype=float)
    return float(np.mean(np.square(values)))


def iter_pairwise_abs_diffs(frame: MeasurementFrame) -> list[float]:
    values = list(frame.dd_values.values())
    diffs: list[float] = []
    for left_index in range(len(values)):
        for right_index in range(left_index + 1, len(values)):
            diffs.append(abs(values[left_index] - values[right_index]))
    return diffs


def estimate_sos_threshold(frames: list[MeasurementFrame], quantile: float) -> float:
    scores = [compute_sos_score(frame) for frame in frames if frame.dd_values]
    clean_scores = [score for score in scores if score is not None]
    if not clean_scores:
        return float("nan")
    return float(np.quantile(np.asarray(clean_scores, dtype=float), quantile))


def estimate_d3_threshold(frames: list[MeasurementFrame], quantile: float) -> float:
    diffs: list[float] = []
    for frame in frames:
        diffs.extend(iter_pairwise_abs_diffs(frame))
    if not diffs:
        return float("nan")
    return float(np.quantile(np.asarray(diffs, dtype=float), quantile))


def calibrate_thresholds(config: CalibrationConfig) -> dict[str, object]:
    file1 = Path(config.file1).resolve()
    file2 = Path(config.file2).resolve()

    LOGGER.info("reading_clean_ubx file1=%s file2=%s", file1, file2)
    epochs1 = read_rawx_epochs(file1, config.max_epochs_per_file)
    epochs2 = read_rawx_epochs(file2, config.max_epochs_per_file)
    matched_pairs = match_epochs(epochs1, epochs2, config.tow_tolerance_s)
    if not matched_pairs:
        raise ValueError("No matched clean epochs found between the two UBX files.")

    LOGGER.info(
        "matched_clean_epochs epochs_rx1=%d epochs_rx2=%d matched=%d",
        len(epochs1),
        len(epochs2),
        len(matched_pairs),
    )
    frames = build_measurement_frames(
        matched_pairs,
        hatch_window=config.hatch_window,
        skip_initial_epochs=config.skip_initial_epochs,
    )

    thresholds = CalibrationResult(
        sos_carrier=estimate_sos_threshold(frames["carrier"], config.sos_clean_quantile),
        sos_smoothed_pseudorange=estimate_sos_threshold(
            frames["smoothed_pseudorange"], config.sos_clean_quantile
        ),
        d3_carrier=estimate_d3_threshold(frames["carrier"], config.d3_clean_quantile),
        d3_smoothed_pseudorange=estimate_d3_threshold(
            frames["smoothed_pseudorange"], config.d3_clean_quantile
        ),
    )

    result = {
        "thresholds": asdict(thresholds),
        "config": asdict(config),
        "summary": {
            "epochs_rx1": len(epochs1),
            "epochs_rx2": len(epochs2),
            "matched_epochs": len(matched_pairs),
            "carrier_frames": len(frames["carrier"]),
            "smoothed_pseudorange_frames": len(frames["smoothed_pseudorange"]),
        },
        "env_suggestion": {
            "SOS_CARRIER_THRESHOLD": thresholds.sos_carrier,
            "SOS_SMOOTHED_PSEUDORANGE_THRESHOLD": thresholds.sos_smoothed_pseudorange,
            "D3_CARRIER_SIMILARITY_THRESHOLD": thresholds.d3_carrier,
            "D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD": thresholds.d3_smoothed_pseudorange,
            "D3_MIN_CLUSTER_SIZE": config.min_cluster_size,
        },
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate initial SoS/D3 thresholds from clean UBX file pairs."
    )
    parser.add_argument("--file1", required=True, help="Clean UBX file for receiver 1.")
    parser.add_argument("--file2", required=True, help="Clean UBX file for receiver 2.")
    parser.add_argument(
        "--output",
        default="output_rt/thresholds/initial_thresholds.json",
        help="JSON output path for calibrated thresholds.",
    )
    parser.add_argument(
        "--tow-tolerance-ms",
        type=float,
        default=20.0,
        help="Maximum allowed TOW mismatch when pairing clean epochs.",
    )
    parser.add_argument(
        "--sos-clean-quantile",
        type=float,
        default=0.05,
        help="Lower clean-data quantile used as the initial SoS threshold.",
    )
    parser.add_argument(
        "--d3-clean-quantile",
        type=float,
        default=0.05,
        help="Lower clean-data quantile used as the initial D3 similarity threshold.",
    )
    parser.add_argument(
        "--skip-initial-epochs",
        type=int,
        default=5,
        help="Discard the first N matched epochs to let the Hatch filter stabilize.",
    )
    parser.add_argument(
        "--hatch-window",
        type=int,
        default=30,
        help="Hatch filter window size for smoothed pseudorange.",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=3,
        help="Reference cluster size to include in the generated config suggestion.",
    )
    parser.add_argument(
        "--max-epochs-per-file",
        type=int,
        default=None,
        help="Read at most N epochs per file, useful for smoke tests.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    config = CalibrationConfig(
        file1=args.file1,
        file2=args.file2,
        output_path=args.output,
        tow_tolerance_s=args.tow_tolerance_ms / 1000.0,
        sos_clean_quantile=args.sos_clean_quantile,
        d3_clean_quantile=args.d3_clean_quantile,
        skip_initial_epochs=args.skip_initial_epochs,
        hatch_window=args.hatch_window,
        min_cluster_size=args.min_cluster_size,
        max_epochs_per_file=args.max_epochs_per_file,
    )
    validate_config(config)
    result = calibrate_thresholds(config)

    output_path = Path(config.output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    LOGGER.info("saved_thresholds output=%s", output_path)


if __name__ == "__main__":
    main()
