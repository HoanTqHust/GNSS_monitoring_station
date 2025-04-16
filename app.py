
import json
import logging
import os
import time
import io
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib
from datetime import datetime
import base64
from multiprocessing import Process
from multiprocessing import Queue

import serial
import psutil
from flask import Flask, render_template, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from pyubx2 import UBXReader
import threading


# ---------- Classes ----------
class SatelliteData:
    def __init__(self, parsed_data, i):
        self.prMes = getattr(parsed_data, f'prMes_{i:02}', None)
        self.cpMes = getattr(parsed_data, f'cpMes_{i:02}', None)
        self.doMes = getattr(parsed_data, f'doMes_{i:02}', None)
        self.gnssId = getattr(parsed_data, f'gnssId_{i:02}', None)
        self.svId = getattr(parsed_data, f'svId_{i:02}', None)
        self.sigId = getattr(parsed_data, f'sigId_{i:02}', None)


class RAWXData:
    def __init__(self, parsed_data):
        self.rcvTow = parsed_data.rcvTow
        self.week = parsed_data.week
        self.satData = []
        for i in range(1, parsed_data.numMeas + 1):
            self.satData.append(SatelliteData(parsed_data, i))


# ---------- Config ----------
# use fix to fix
fix = 0
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
data_queue = Queue(maxsize=1000)    # queue use to send data from read uart thread to draw thread

with open("config.json", "r") as file:
    config = json.load(file)


BUFFER_SAMPLES = 30
PLOT_INTERVAL = 2.0

# ---------- Helper Functions ----------
def append_with_limit(queue, item, maxlen=BUFFER_SAMPLES):
    queue.append(item)
    if len(queue) > maxlen:
        del queue[0]

def read_serial():
    port1 = "/dev/ttyACM0"
    port2 = "/dev/ttyACM1"
    ser1 = serial.Serial(port1, baudrate=38400, timeout=1)
    ser2 = serial.Serial(port2, baudrate=38400, timeout=1)
    ubr1 = UBXReader(ser1, protfilter=2)
    ubr2 = UBXReader(ser2, protfilter=2)
    timer = 0
    rawx1 = rawx2 = nav1 = nav2 = None

    skyplot_data_1 = ""
    spectrum_data_1 = ""
    skyplot_data_2 = ""
    spectrum_data_2 = ""
    combined_samples = []

    while True:
        try:
            raw_data_1, parsed_data_1 = ubr1.read()
            raw_data_2, parsed_data_2 = ubr2.read()
            if (raw_data_1 is None) or (raw_data_2 is None):
                continue
#            print(parsed_data_1)
 #           print(parsed_data_2)
            if parsed_data_1.identity == "NAV-SAT":
                skyplot_data_1 = parsed_data_1

            if parsed_data_1.identity == "MON-SPAN":
                spectrum_data_1 = parsed_data_1

            if parsed_data_1.identity == "RXM-RAWX":
                rawx1 = RAWXData(parsed_data_1)
            if parsed_data_1.identity == "NAV-PVT":
                nav1 = parsed_data_1

            if parsed_data_2.identity == "NAV-SAT":
                skyplot_data_2 = parsed_data_2

            if parsed_data_2.identity == "MON-SPAN":
                spectrum_data_2 = parsed_data_2

            if parsed_data_2.identity == "RXM-RAWX":
                rawx2 = RAWXData(parsed_data_2)
            if parsed_data_2.identity == "NAV-PVT":
                nav2 = parsed_data_2

            # Append only if both devices have valid RAWX and NAV-PVT
            if rawx1 and nav1 and rawx2 and nav2 and (round(rawx1.rcvTow) == round(rawx2.rcvTow)):
            # if rawx1 and nav1 and rawx2 and nav2:
                print(f"{rawx1.rcvTow} and {rawx2.rcvTow}")
                append_with_limit(combined_samples, (rawx1, nav1, rawx2, nav2))
                rawx1 = rawx2 = nav1 = nav2 = None
                try:
                    if data_queue.full():
                        data_queue.get_nowait()  # bỏ phần tử cũ
                    data_queue.put((combined_samples, skyplot_data_1, skyplot_data_2, spectrum_data_1, spectrum_data_2))
                except Exception as e:
                    print("Queue put error:", e)
        except Exception as e:
            print("Error in get ublox data thread:", e)

def calc_pseudorange(rxmRaw, navPvt):
    ps = np.zeros(32)
    for sat in rxmRaw.satData:
        if sat.gnssId == 0 and sat.sigId == 0:  # GPS L1 only
            try:
                sv_index = sat.svId - 1
                ps[sv_index] = sat.cpMes + float(navPvt.nano) * 1e-9 * float(sat.doMes)
            except:
                continue
    return ps, np.zeros(32)

def process_ubx_data(combined_samples):
    if len(combined_samples) < BUFFER_SAMPLES:
        return

    print(f"[INFO] Plotting with {BUFFER_SAMPLES} samples")

    dps = np.zeros((BUFFER_SAMPLES, 32))
    svId_to_idx = {}
    idx_to_svId = {}
    sv_counter = 0

    for idx in range(BUFFER_SAMPLES):
        (rawx1, nav1, rawx2, nav2) = combined_samples[idx]

        ps1, _ = calc_pseudorange(rawx1, nav1)
        ps2, _ = calc_pseudorange(rawx2, nav2)

        for i in range(32):
            if ps1[i] != 0 and ps2[i] != 0:
                svId = i + 1
                if svId not in svId_to_idx:
                    svId_to_idx[svId] = sv_counter
                    idx_to_svId[sv_counter] = svId
                    sv_counter += 1
                dps[idx, svId_to_idx[svId]] = ps1[i] - ps2[i]

        if sv_counter > 0:
            dps[idx, :] -= dps[idx, 0]
        dps[idx, :] -= np.round(dps[idx, :])

    valid_columns = np.any(dps != 0, axis=0)
    dps_trimmed = dps[:, valid_columns]
    print(dps_trimmed)
    svIds = [svId for svId, idx in svId_to_idx.items() if valid_columns[idx]]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
    for i, svId in enumerate(svIds):
        axes[0].plot(dps_trimmed[:, i], label=f'SV {svId}', alpha=0.8)

    axes[0].legend(ncol=4, fontsize=8)
    axes[0].grid(True)
    axes[0].set_xlabel('Time Index')
    axes[0].set_ylabel('Pseudorange Difference (m)')
    axes[0].set_title('Sliding Window Pseudorange Differences')

    sns.heatmap(dps_trimmed.T, cmap="coolwarm", cbar=True, ax=axes[1], linewidths=0.5)
    axes[1].set_yticks(np.arange(len(svIds)) + 0.5)
    axes[1].set_yticklabels([f"SV {svId}" for svId in svIds], rotation=0)
    axes[1].set_xlabel("Time Index")
    axes[1].set_ylabel("Satellite SV ID")
    axes[1].set_title("Heatmap of Pseudorange Differences")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    mean_abs_dps = np.abs(np.mean(dps_trimmed, axis=0))
    mean_abs_all = np.mean(np.abs(dps_trimmed))
    return buf


def processData(parsed_data):
    satellites = []
    try:
        if parsed_data and parsed_data.identity == "NAV-SAT":
            for i in range(1, parsed_data.numSvs + 1):
                prn = getattr(parsed_data, f'svId_{i:02}', None)
                azim = getattr(parsed_data, f'azim_{i:02}', None)
                elev = getattr(parsed_data, f'elev_{i:02}', None)
                if prn is not None and azim is not None and elev is not None:
                    satellites.append({'prn': prn, 'azim': azim, 'elev': elev})
            time.sleep(1)
    except Exception as e:
        print("Error reading UBX data:", e)
    return satellites


def processDataMonSpan(parsed_data):
    """
    Xử lý dữ liệu từ MON-SPAN message và trả về một dictionary chứa các trường cần thiết.
    Bao gồm cả các mảng dữ liệu phổ (spectrum_01, spectrum_02).
    """
    mon_span_data = {}
    try:
        if parsed_data and parsed_data.identity == "MON-SPAN":
            # Lặp qua các thuộc tính không ẩn của parsed_data
            for attr in dir(parsed_data):
                if not attr.startswith('_'):
                    try:
                        value = getattr(parsed_data, attr)
                        if isinstance(value, (int, float, str)):
                            mon_span_data[attr] = value
                        # Nếu thuộc tính là list và tên bắt đầu bằng "spectrum_", thêm vào dictionary
                        elif isinstance(value, list) and attr.startswith("spectrum_"):
                            mon_span_data[attr] = value
                    except Exception as e:
                        print(f"Error reading attribute {attr}: {e}")
    except Exception as e:
        print("Error processing MON-SPAN data:", e)
    return mon_span_data


def create_spectrum_plot(mon_span_data):
    spec1 = mon_span_data.get("spectrum_01")
    spec2 = mon_span_data.get("spectrum_02")

    fig, axs = plt.subplots(2, 1, figsize=(8, 6))

    if spec1 is not None:
        n_bins1 = len(spec1)
        span1 = mon_span_data.get("span_01")
        center1 = mon_span_data.get("center_01")
        # Tính trục tần số cho spec1: từ (center - span/2) đến (center + span/2)
        freq_start1 = center1 - span1 / 2
        freq_end1 = center1 + span1 / 2
        frequencies1 = np.linspace(freq_start1, freq_end1, n_bins1)

        axs[0].plot(frequencies1, spec1, color='blue')
        axs[0].set_title("Spectrum 01")
        axs[0].set_xlabel("Frequency (GHz)")
        axs[0].set_ylabel("Amplitude")
    else:
        axs[0].axis('off')

    if spec2 is not None:
        n_bins2 = len(spec2)
        span2 = mon_span_data.get("span_02")
        center2 = mon_span_data.get("center_02")
        freq_start2 = center2 - span2 / 2
        freq_end2 = center2 + span2 / 2
        frequencies2 = np.linspace(freq_start2, freq_end2, n_bins2)

        axs[1].plot(frequencies2, spec2, color='green')
        axs[1].set_title("Spectrum 02")
        axs[1].set_xlabel("Frequency (GHz)")
        axs[1].set_ylabel("Amplitude")
    else:
        axs[1].axis('off')

    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def create_skyplot(satellites):
    """Create a skyplot PNG image from the current satellite data."""
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, polar=True)
    # ax.set_aspect('equal',adjustable='datalim')
    # Configure the polar plot:
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 90)
    ax.set_yticks(range(0, 91, 10))
    ax.set_yticklabels([f"{90 - deg}°" for deg in range(0, 91, 10)])

    for sat in satellites:
        r = 90 - sat['elev']
        theta = np.deg2rad(sat['azim'])
        ax.plot(theta, r, 'o', label=f"PRN {sat['prn']}")
        ax.text(theta, r, f"{sat['prn']}", fontsize=8, ha='center', va='bottom')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


def encode_image(buf):
    with buf:
        return base64.b64encode(buf.getvalue()).decode('utf-8')

@socketio.on('connect')
def handle_connect():
    print("Client connected")
# background socket
def background_thread():
    last_plot_time = time.time()
    while True:
        try:
            # Plot if enough time passed and buffer is full
            current_time = time.time()
            dps_plot = ""
            cpu_load = psutil.cpu_percent(interval=0.5)
            combined_samples, skyplot_data_1, skyplot_data_2, spectrum_data_1, spectrum_data_2 = data_queue.get()
            if current_time - last_plot_time >= PLOT_INTERVAL:
                dps_plot_data = process_ubx_data(combined_samples)
                last_plot_time = current_time
                dps_plot = encode_image(dps_plot_data)
            if (dps_plot == ""):
                print("Dont send")
            else:
                # Create 'data' directory if it doesn't exist
                # os.makedirs("data", exist_ok=True)
                # Get current timestamp as filename
                # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # filename = f"data/dps_{timestamp}.png"
                # Decode base64 and save to file
                # with open(filename, "wb") as f:
                #    f.write(base64.b64decode(dps_plot))
                skyplot_1 = encode_image(create_skyplot(processData(skyplot_data_1)))
                skyplot_2 = encode_image(create_skyplot(processData(skyplot_data_2)))
                spectrum_1 = encode_image(create_spectrum_plot(processDataMonSpan(spectrum_data_1)))
                spectrum_2 = encode_image(create_spectrum_plot(processDataMonSpan(spectrum_data_2)))
                socketio.emit("update_image", {
                    "skyplot1": "data:image/png;base64," + skyplot_1,
                    "spectrum1": "data:image/png;base64," + spectrum_1,
                    "skyplot2": "data:image/png;base64," + skyplot_2,
                    "spectrum2": "data:image/png;base64," + spectrum_2,
                    "cpu_load": cpu_load,
                    "dps": "data:image/png;base64," + dps_plot,
                })
        except Exception as e:
            print("Error in background thread:", e)


if __name__ == "__main__":
    serial_process = Process(target=read_serial)
    serial_process.start()

    socketio.start_background_task(background_thread)
    try:
        logging.debug("Starting Flask app...")
        socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
