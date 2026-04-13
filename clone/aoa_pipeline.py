#!/usr/bin/env python3
"""
Pipeline AOA/DD chuyển từ notebook AOA_Paper.ipynb sang script chạy batch.

Mục tiêu chính của file:
1) Đọc raw UBX của 2 receiver u-blox ở 2 bối cảnh:
   - Non-SP (không spoofing)
   - SP (có spoofing)
2) Đồng bộ 2 luồng đo theo GPS Time Of Week (TOW).
3) Tạo đặc trưng DD (double-difference theo chu kỳ sóng mang) giữa 2 receiver.
4) Suy ra/gom các đại lượng góc AOA:
   - Từ ephemeris (NAV-SAT)
   - Từ DD
5) Vẽ các đồ thị để quan sát sai khác normal vs spoofing, sau đó xuất bảng
   so sánh DD-vs-ephemeris ra Excel.

Lưu ý: script này thiên về tái hiện đúng workflow nghiên cứu trong notebook
để phân tích/đánh giá spoofing, chưa phải pipeline realtime.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyubx2 import UBXReader


class UBXData:
    def __init__(self) -> None:
        # Gom các bản tin UBX theo từng loại để truy cập theo epoch dễ hơn.
        self.navClocks = []
        self.navPvts = []
        self.rxmRaws = []
        self.navSats = []


class RAWXData:
    def __init__(self, parsed_data) -> None:
        # Header của 1 bản tin RXM-RAWX (1 epoch đo).
        self.rcvTow = parsed_data.rcvTow
        self.week = parsed_data.week
        self.leapS = parsed_data.leapS
        self.numMeas = parsed_data.numMeas
        self.satData = []
        for i in range(1, parsed_data.numMeas + 1):
            self.satData.append(SatelliteData(parsed_data, i))


class SatelliteData:
    def __init__(self, parsed_data, i: int) -> None:
        # Mỗi object biểu diễn 1 vệ tinh trong cùng epoch RAWX.
        self.prMes = getattr(parsed_data, f"prMes_{i:02}", None)
        self.cpMes = getattr(parsed_data, f"cpMes_{i:02}", None)
        self.doMes = getattr(parsed_data, f"doMes_{i:02}", None)
        self.gnssId = getattr(parsed_data, f"gnssId_{i:02}", None)
        self.svId = getattr(parsed_data, f"svId_{i:02}", None)
        self.sigId = getattr(parsed_data, f"sigId_{i:02}", None)
        self.freqId = getattr(parsed_data, f"freqId_{i:02}", None)
        self.locktime = getattr(parsed_data, f"locktime_{i:02}", None)
        self.cno = getattr(parsed_data, f"cno_{i:02}", None)
        self.prStdev = getattr(parsed_data, f"prStd_{i:02}", None)
        self.cpStdev = getattr(parsed_data, f"cpStd_{i:02}", None)
        self.doStdev = getattr(parsed_data, f"doStd_{i:02}", None)
        self.trkStat = getattr(parsed_data, f"trkStat_{i:02}", None)


@dataclass
class AnalysisConfig:
    length: int
    start_index: int
    alpha_r_deg: float
    bias_angle: float
    selected_svids: list[int]
    minus_one_svids: set[int]
    output_dir_name: str
    include_normal_dd_plot: bool


def resolve_base_path(start_dir: Path) -> Path:
    candidates = [start_dir.resolve(), start_dir.resolve().parent]
    for base in candidates:
        if (base / "data" / "Non-SP" / "raw_data_1.ubx").exists():
            return base
    raise FileNotFoundError(
        "Cannot find data files. Expected: data/Non-SP/raw_data_1.ubx from current script dir or parent."
    )


def read_ubx_file(file_path: Path) -> UBXData:
    """Đọc file UBX và chỉ giữ các message cần cho pipeline AOA/DD."""
    raw_data_all = UBXData()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("rb") as file:
        reader = UBXReader(file, protfilter=2)
        for _, parsed_data in reader:
            identity = parsed_data.identity
            if identity == "RXM-RAWX":
                raw_data_all.rxmRaws.append(RAWXData(parsed_data))
            elif identity == "NAV-CLOCK":
                raw_data_all.navClocks.append(parsed_data)
            elif identity == "NAV-PVT":
                raw_data_all.navPvts.append(parsed_data)
            elif identity == "NAV-SAT":
                raw_data_all.navSats.append(parsed_data)
    return raw_data_all


def sync_by_tow(data1: UBXData, data2: UBXData) -> tuple[UBXData, UBXData]:
    """
    Cắt đầu chuỗi để 2 receiver bắt đầu cùng mốc thời gian TOW.

    offset > 0: data2 đi chậm -> bỏ bớt đầu data2
    offset < 0: data1 đi chậm -> bỏ bớt đầu data1
    """
    if not data1.rxmRaws or not data2.rxmRaws:
        return data1, data2

    offset = int(float(data1.rxmRaws[0].rcvTow) - float(data2.rxmRaws[0].rcvTow))
    if offset > 0:
        data2.navPvts = data2.navPvts[offset:]
        data2.navClocks = data2.navClocks[offset:]
        data2.rxmRaws = data2.rxmRaws[offset:]
        data2.navSats = data2.navSats[offset:]
    elif offset < 0:
        offset = abs(offset)
        data1.navPvts = data1.navPvts[offset:]
        data1.navClocks = data1.navClocks[offset:]
        data1.rxmRaws = data1.rxmRaws[offset:]
        data1.navSats = data1.navSats[offset:]
    return data1, data2


def calc_pseudorange(rxm_raw: RAWXData, nav_pvt) -> tuple[np.ndarray, np.ndarray]:
    """
    Tính vector quan sát theo từng SV (GPS L1: gnssId=0, sigId=0).

    Theo notebook gốc, giá trị dùng cho DD được xây từ carrier phase cpMes và
    hiệu chỉnh phần nano-second qua doMes.
    """
    ps = np.zeros(32)
    bias = np.zeros(32)
    for sat in rxm_raw.satData:
        if sat.gnssId == 0 and sat.sigId == 0 and sat.svId is not None:
            ps[sat.svId - 1] = sat.cpMes + float(nav_pvt.nano) * 1e-9 * float(sat.doMes)
    return ps, bias


def compute_dps(
    raw_data_1: UBXData, raw_data_2: UBXData, start_index: int = 0, data_length: int = 150
) -> tuple[np.ndarray, list[int]]:
    """
    Tạo ma trận DD (dps) giữa 2 receiver theo thời gian.

    Mỗi epoch:
    1) Lấy quan sát vệ tinh từ receiver #1 và #2.
    2) Tính sai khác đơn giữa 2 receiver cho từng SV.
    3) Lấy SV đầu tiên làm vệ tinh tham chiếu -> trừ đi cột tham chiếu
       để được double-difference.
    4) Trừ phần nguyên (round) để giữ phần dư theo cycle-slip/fringe
       trong khoảng xấp xỉ [-0.5, 0.5], thuận tiện quan sát bất thường.
    """
    dps = np.zeros((data_length, 32))
    sv_id_to_col: dict[int, int] = {}
    next_col = 0

    for row_idx in range(data_length):
        data_idx = start_index + row_idx
        if data_idx >= len(raw_data_1.rxmRaws) or data_idx >= len(raw_data_2.rxmRaws):
            break
        if data_idx >= len(raw_data_1.navPvts) or data_idx >= len(raw_data_2.navPvts):
            break

        sat_data_1 = raw_data_1.rxmRaws[data_idx]
        nav_pvt_1 = raw_data_1.navPvts[data_idx]
        ps1, bs1 = calc_pseudorange(sat_data_1, nav_pvt_1)

        sat_data_2 = raw_data_2.rxmRaws[data_idx]
        nav_pvt_2 = raw_data_2.navPvts[data_idx]
        ps2, bs2 = calc_pseudorange(sat_data_2, nav_pvt_2)

        ps1 += bs1
        ps2 += bs2

        for sat_idx in range(32):
            if ps1[sat_idx] != 0 and ps2[sat_idx] != 0:
                sv_id = sat_idx + 1
                if sv_id not in sv_id_to_col:
                    # Cố định ánh xạ SV -> cột để chuỗi thời gian không bị lệch cột.
                    sv_id_to_col[sv_id] = next_col
                    next_col += 1
                col = sv_id_to_col[sv_id]
                dps[row_idx, col] = ps1[sat_idx] - ps2[sat_idx]

        if next_col > 0:
            # Double-difference theo SV tham chiếu (cột 0).
            dps[row_idx, :] -= dps[row_idx, 0]
            # Bỏ phần nguyên chu kỳ để tập trung vào sai khác phân số.
            dps[row_idx, :] -= np.round(dps[row_idx, :])

    valid_columns = np.any(dps != 0, axis=0)
    dps_trimmed = dps[:, valid_columns]

    sv_ids = []
    for sv_id, col in sorted(sv_id_to_col.items(), key=lambda x: x[1]):
        if col < len(valid_columns) and valid_columns[col]:
            sv_ids.append(sv_id)
    return dps_trimmed, sv_ids


def psi_i_deg(alpha_r_deg: float, alpha_i_deg: float) -> float:
    """
    Psi_i = cos(alpha_i) - cos(alpha_r), chuẩn hóa theo modulo 1 cycle.
    """
    alpha_i_rad = math.radians(alpha_i_deg)
    alpha_r_rad = math.radians(alpha_r_deg)
    diff = math.cos(alpha_i_rad) - math.cos(alpha_r_rad)
    return diff - round(diff)


def save_fig(fig, filename: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "eps"):
        fig.savefig(output_dir / f"{filename}.{ext}", format=ext, dpi=300)
    plt.close(fig)


def extract_psi_and_alpha_from_navsats(
    nav_sats: list, start_index: int, length: int, bias_angle: float
) -> tuple[dict[int, list[float]], dict[int, list[float]]]:
    """
    Trích xuất chuỗi alpha_i và psi_i từ NAV-SAT (ephemeris + góc nhìn vệ tinh).

    - Chỉ dùng GPS (gnssId=0)
    - Quy đổi (elev, azim) -> alpha_i theo mô hình hình học của notebook
    - psi_i được tính tương đối theo vệ tinh tham chiếu đầu tiên mỗi epoch
    """
    psi_timeseries: dict[int, list[float]] = {}
    alpha_deg_timeseries: dict[int, list[float]] = {}

    for msg in nav_sats[start_index : start_index + length]:
        gps_sats: list[tuple[int, float]] = []
        num_svs = int(getattr(msg, "numSvs", 0))
        for i in range(1, num_svs + 1):
            gnss = getattr(msg, f"gnssId_{i:02d}", None)
            if gnss != 0:
                continue
            svid = getattr(msg, f"svId_{i:02d}", None)
            elev = getattr(msg, f"elev_{i:02d}", None)
            azim = getattr(msg, f"azim_{i:02d}", None)
            if svid is None or elev is None or azim is None:
                continue

            elev_rad = math.radians(elev)
            azim_rad = math.radians(azim - bias_angle)
            cos_val = math.cos(elev_rad) * math.cos(azim_rad)
            value_deg = math.degrees(math.acos(np.clip(cos_val, -1.0, 1.0)))
            gps_sats.append((svid, value_deg))

        if gps_sats:
            alpha_r_val_deg = gps_sats[0][1]
            for svid, alpha_i_val_deg in gps_sats:
                psi_val = psi_i_deg(alpha_r_val_deg, alpha_i_val_deg)
                psi_timeseries.setdefault(svid, []).append(psi_val)
                alpha_deg_timeseries.setdefault(svid, []).append(alpha_i_val_deg)

    return psi_timeseries, alpha_deg_timeseries


def pad_series(values: np.ndarray, target_len: int) -> np.ndarray:
    padded = np.full(target_len, np.nan, dtype=float)
    n = min(target_len, len(values))
    padded[:n] = values[:n]
    return padded


def plot_dd(
    dps: np.ndarray,
    sv_ids: list[int],
    output_dir: Path,
    filename: str,
    excluded_svids: set[int],
    xlabel: str | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    for col, svid in enumerate(sv_ids):
        if svid in excluded_svids:
            continue
        ax.plot(dps[:, col], label=f"SV {svid}", linestyle="-", alpha=0.8)
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.set_ylabel("DD values (in cycles)")
    ax.set_ylim([-0.5, 0.5])
    ax.legend(ncol=4, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    save_fig(fig, filename, output_dir)


def plot_selected_series(
    data_by_svid: dict[int, list[float]],
    selected_svids: list[int],
    length: int,
    output_dir: Path,
    filename: str,
    ylabel: str,
    transform=None,
    ylim: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    epochs = np.arange(length)

    for svid in selected_svids:
        if svid not in data_by_svid:
            continue
        y = np.asarray(data_by_svid[svid], dtype=float)
        if transform is not None:
            y = transform(y)
        y = pad_series(y, length)
        ax.plot(epochs, y, label=f"SV {svid}", linestyle="-", alpha=0.8)

    ax.set_ylabel(ylabel)
    ax.set_xlabel("Time Index")
    if ylim is not None:
        ax.set_ylim(list(ylim))
    ax.legend(ncol=4, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    save_fig(fig, filename, output_dir)


def plot_from_dd(
    dps: np.ndarray,
    sv_ids: list[int],
    selected_svids: list[int],
    length: int,
    output_dir: Path,
    filename: str,
    cos_alpha_r: float,
    minus_one_svids: set[int],
    to_alpha_deg: bool,
    ylabel: str,
    ylim: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    epochs = np.arange(length)
    selected_set = set(selected_svids)

    for col, svid in enumerate(sv_ids):
        if svid not in selected_set:
            continue
        # Dự đoán cos(alpha_i) từ DD theo công thức của notebook.
        y_pred = dps[:, col] + cos_alpha_r
        if svid in minus_one_svids:
            # Một số SV cần offset -1 để unwrap đúng pha.
            y_pred = y_pred - 1.0

        if to_alpha_deg:
            y_plot = np.degrees(np.arccos(np.clip(y_pred, -1.0, 1.0)))
        else:
            y_plot = y_pred

        y_plot = pad_series(y_plot, length)
        ax.plot(epochs, y_plot, label=f"SV {svid}", linestyle="-", alpha=0.8)

    ax.set_ylabel(ylabel)
    ax.set_xlabel("Time Index")
    if ylim is not None:
        ax.set_ylim(list(ylim))
    ax.legend(ncol=4, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    save_fig(fig, filename, output_dir)


def build_dd_alpha_data(
    dps: np.ndarray,
    sv_ids: list[int],
    selected_svids: list[int],
    length: int,
    cos_alpha_r: float,
    minus_one_svids: set[int],
) -> dict[int, np.ndarray]:
    """Chuẩn hóa dữ liệu alpha suy từ DD để so với ephemeris."""
    dd_data: dict[int, np.ndarray] = {}
    selected_set = set(selected_svids)
    for col, svid in enumerate(sv_ids):
        if svid not in selected_set:
            continue
        y_pred = dps[:, col] + cos_alpha_r
        if svid in minus_one_svids:
            y_pred = y_pred - 1.0
        y_alpha_deg = np.degrees(np.arccos(np.clip(y_pred, -1.0, 1.0)))
        dd_data[svid] = y_alpha_deg[:length]
    return dd_data


def build_eph_alpha_data(
    alpha_deg_timeseries: dict[int, list[float]],
    selected_svids: list[int],
    length: int,
) -> dict[int, np.ndarray]:
    """Chuẩn hóa dữ liệu alpha lấy từ ephemeris (NAV-SAT)."""
    eph_data: dict[int, np.ndarray] = {}
    for svid in selected_svids:
        if svid not in alpha_deg_timeseries:
            continue
        eph_data[svid] = np.asarray(alpha_deg_timeseries[svid][:length], dtype=float)
    return eph_data


def compare_dd_vs_eph(
    eph_data: dict[int, np.ndarray],
    dd_data: dict[int, np.ndarray],
    thresholds: tuple[int, ...] = (5, 7, 10),
) -> pd.DataFrame:
    """
    So sánh |alpha_DD - alpha_ephemeris| theo ngưỡng lỗi.

    Mặc định đánh giá tại 5/7/10 độ, và áp dụng rule tại 10 độ:
    tỷ lệ mẫu đạt > 75% => OK.
    """
    rows = []
    common_svids = sorted(set(eph_data.keys()) & set(dd_data.keys()))

    for thr in thresholds:
        all_abs_errors = []
        for svid in common_svids:
            eph = eph_data[svid]
            dd = dd_data[svid]
            n = min(len(eph), len(dd))
            if n == 0:
                continue

            abs_err = np.abs(dd[:n] - eph[:n])
            all_abs_errors.append(abs_err)

            bins_ok = int(np.sum(abs_err <= thr))
            bins_total = int(n)
            frac_ok = bins_ok / bins_total

            rule = ""
            if thr == 10:
                rule = "OK" if frac_ok > 0.75 else "NOT OK"

            rows.append(
                {
                    "SV": svid,
                    "threshold": f"{thr} deg",
                    "bins_ok": bins_ok,
                    "bins_total": bins_total,
                    "fraction_ok": round(frac_ok, 3),
                    "rule_5deg": rule,
                }
            )

        if all_abs_errors:
            abs_err_all = np.concatenate(all_abs_errors)
            bins_ok_all = int(np.sum(abs_err_all <= thr))
            bins_total_all = int(len(abs_err_all))
            frac_ok_all = bins_ok_all / bins_total_all
        else:
            bins_ok_all = 0
            bins_total_all = 0
            frac_ok_all = float("nan")

        rule_all = ""
        if thr == 10 and not np.isnan(frac_ok_all):
            rule_all = "OK" if frac_ok_all > 0.75 else "NOT OK"

        rows.append(
            {
                "SV": "ALL",
                "threshold": f"{thr} deg",
                "bins_ok": bins_ok_all,
                "bins_total": bins_total_all,
                "fraction_ok": round(frac_ok_all, 3) if not np.isnan(frac_ok_all) else np.nan,
                "rule_5deg": rule_all,
            }
        )
    return pd.DataFrame(rows)


def run_analysis_block(
    nav_data_for_psi: UBXData,
    dps_for_dd: np.ndarray,
    sv_ids_for_dd: list[int],
    output_dir: Path,
    config: AnalysisConfig,
) -> dict[str, object]:
    """
    Chạy trọn một block phân tích:
    - Lấy psi/alpha từ NAV-SAT
    - Vẽ các đồ thị reverse_dd, cos(alpha), aoa (từ DD và từ ephemeris)
    - Trả về biến trung gian cho block so sánh cuối
    """
    psi_timeseries, alpha_deg_timeseries = extract_psi_and_alpha_from_navsats(
        nav_data_for_psi.navSats,
        start_index=config.start_index,
        length=config.length,
        bias_angle=config.bias_angle,
    )

    plot_selected_series(
        psi_timeseries,
        selected_svids=config.selected_svids,
        length=config.length,
        output_dir=output_dir,
        filename="reverse_dd",
        ylabel="DD values (in cycles)",
        ylim=(-0.5, 0.5),
    )

    plot_selected_series(
        alpha_deg_timeseries,
        selected_svids=config.selected_svids,
        length=config.length,
        output_dir=output_dir,
        filename="cos_alpha_i_from_ephemeris",
        ylabel=r"$\cos(\alpha_i)$",
        transform=lambda y: np.cos(np.radians(y)),
    )

    cos_alpha_r = math.cos(math.radians(config.alpha_r_deg))
    plot_from_dd(
        dps_for_dd,
        sv_ids_for_dd,
        selected_svids=config.selected_svids,
        length=config.length,
        output_dir=output_dir,
        filename="cos_alpha_i_from_dd",
        cos_alpha_r=cos_alpha_r,
        minus_one_svids=config.minus_one_svids,
        to_alpha_deg=False,
        ylabel=r"$\cos(\alpha_i)$",
        ylim=(-1.0, 1.0),
    )

    plot_from_dd(
        dps_for_dd,
        sv_ids_for_dd,
        selected_svids=config.selected_svids,
        length=config.length,
        output_dir=output_dir,
        filename="aoa_from_dd",
        cos_alpha_r=cos_alpha_r,
        minus_one_svids=config.minus_one_svids,
        to_alpha_deg=True,
        ylabel=r"$\alpha_i$ (in degree)",
        ylim=(0.0, 180.0),
    )

    plot_selected_series(
        alpha_deg_timeseries,
        selected_svids=config.selected_svids,
        length=config.length,
        output_dir=output_dir,
        filename="aoa_from_ephemeris",
        ylabel=r"$\alpha_i$ (in degree)",
        ylim=(0.0, 180.0),
    )

    return {
        "psi_timeseries": psi_timeseries,
        "alpha_deg_timeseries": alpha_deg_timeseries,
        "cos_alpha_r": cos_alpha_r,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full AOA pipeline from notebook in one script.")
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Base directory containing data/Non-SP and data/SP. Default: auto-detect from script dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save all outputs. Default: <script_dir>/output.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    base_dir = Path(args.base_dir).resolve() if args.base_dir else resolve_base_path(script_dir)
    output_root = Path(args.output_dir).resolve() if args.output_dir else (script_dir / "output")
    output_root.mkdir(parents=True, exist_ok=True)

    normal_file_1 = base_dir / "data" / "Non-SP" / "raw_data_1.ubx"
    normal_file_2 = base_dir / "data" / "Non-SP" / "raw_data_2.ubx"
    spoofing_file_1 = base_dir / "data" / "SP" / "raw_data_1.ubx"
    spoofing_file_2 = base_dir / "data" / "SP" / "raw_data_2.ubx"

    print(f"Using base_dir: {base_dir}")
    print(f"Using output_dir: {output_root}")
    print("Reading normal files:")
    print(f" - {normal_file_1}")
    print(f" - {normal_file_2}")
    normal_data_1 = read_ubx_file(normal_file_1)
    normal_data_2 = read_ubx_file(normal_file_2)

    print("Reading spoofing files:")
    print(f" - {spoofing_file_1}")
    print(f" - {spoofing_file_2}")
    spoofing_data_1 = read_ubx_file(spoofing_file_1)
    spoofing_data_2 = read_ubx_file(spoofing_file_2)

    normal_data_1, normal_data_2 = sync_by_tow(normal_data_1, normal_data_2)
    spoofing_data_1, spoofing_data_2 = sync_by_tow(spoofing_data_1, spoofing_data_2)

    # Block 1: cấu hình theo kịch bản trong notebook (cell #3).
    # Dùng dữ liệu normal để tạo baseline và làm đầu vào cho block so sánh.
    cfg_normal = AnalysisConfig(
        length=200,
        start_index=4000,
        alpha_r_deg=53.89629,
        bias_angle=16.0,
        selected_svids=[15, 18, 23, 24, 25, 28, 32],
        minus_one_svids={18, 25, 28},
        output_dir_name="NonSpoofing_Results_200s",
        include_normal_dd_plot=True,
    )

    out_dir_normal = output_root / "Plot" / "AOA" / cfg_normal.output_dir_name
    spoof_dps_1, spoof_sv_ids_1 = compute_dps(
        spoofing_data_1, spoofing_data_2, start_index=0, data_length=cfg_normal.length
    )
    # DD của normal lấy tại start_index lớn (theo thực nghiệm trong notebook).
    normal_dps, normal_sv_ids = compute_dps(
        normal_data_1,
        normal_data_2,
        start_index=cfg_normal.start_index,
        data_length=cfg_normal.length,
    )

    plot_dd(
        spoof_dps_1,
        spoof_sv_ids_1,
        output_dir=out_dir_normal,
        filename="dd_spoofing",
        excluded_svids={1, 3, 30, 12},
    )
    if cfg_normal.include_normal_dd_plot:
        plot_dd(
            normal_dps,
            normal_sv_ids,
            output_dir=out_dir_normal,
            filename="dd_normal",
            excluded_svids={12},
            xlabel="Time Index",
        )

    normal_block_result = run_analysis_block(
        nav_data_for_psi=normal_data_1,
        dps_for_dd=normal_dps,
        sv_ids_for_dd=normal_sv_ids,
        output_dir=out_dir_normal,
        config=cfg_normal,
    )

    # Block 2: cấu hình cho tập spoofing (cell #4), tập trung quan sát khi có tấn công.
    cfg_spoof = AnalysisConfig(
        length=200,
        start_index=0,
        alpha_r_deg=40.83,
        bias_angle=10.0,
        selected_svids=[13, 15, 18, 20, 23, 24, 29],
        minus_one_svids=set(),
        output_dir_name="Results_Spoofing_200s",
        include_normal_dd_plot=False,
    )

    out_dir_spoof = output_root / "Plot" / "AOA" / cfg_spoof.output_dir_name
    spoof_dps_2, spoof_sv_ids_2 = compute_dps(
        spoofing_data_1,
        spoofing_data_2,
        start_index=0,
        data_length=cfg_spoof.length,
    )
    plot_dd(
        spoof_dps_2,
        spoof_sv_ids_2,
        output_dir=out_dir_spoof,
        filename="dd_spoofing",
        excluded_svids={1, 3, 30, 12},
    )
    run_analysis_block(
        nav_data_for_psi=spoofing_data_1,
        dps_for_dd=spoof_dps_2,
        sv_ids_for_dd=spoof_sv_ids_2,
        output_dir=out_dir_spoof,
        config=cfg_spoof,
    )

    # Block so sánh cuối (cell #5): đối chiếu alpha từ DD và từ ephemeris.
    eph_data = build_eph_alpha_data(
        alpha_deg_timeseries=normal_block_result["alpha_deg_timeseries"],
        selected_svids=cfg_normal.selected_svids,
        length=cfg_normal.length,
    )
    dd_data = build_dd_alpha_data(
        dps=normal_dps,
        sv_ids=normal_sv_ids,
        selected_svids=cfg_normal.selected_svids,
        length=cfg_normal.length,
        cos_alpha_r=normal_block_result["cos_alpha_r"],
        minus_one_svids=cfg_normal.minus_one_svids,
    )

    df_compare = compare_dd_vs_eph(eph_data, dd_data)
    excel_output = output_root / "compare_dd_vs_ephemeris_deg.xlsx"
    df_compare.to_excel(excel_output, index=False)

    print(df_compare.to_string(index=False))
    print(f"Saved comparison to: {excel_output}")
    print("Pipeline completed.")


if __name__ == "__main__":
    main()
