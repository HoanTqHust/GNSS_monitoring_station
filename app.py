import json
import logging
import time
import io
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import base64
import serial
import psutil
from flask import Flask, render_template, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from connect.connect import UBXConnector
from process.process import MessageProcessor
from pyubx2 import UBXReader

matplotlib.use('Agg')
matplotlib.rcParams['font.family'] = 'Arial'
# use fix to fix
fix = 1
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

with open("config.json", "r") as file:
    config = json.load(file)

# ubx_connector = UBXConnector(config)
# ubx_connector.start()
# ubx_processor = MessageProcessor(ubx_connector.data_queue)
# ubx_processor.start()
port1 = "/dev/tty.usbmodem21401"
port2 = "/dev/tty.usbmodem21201"
# get data from serial COM5 and COM6 (COM6 haven't set)
ser1 = serial.Serial(port1, baudrate=115200, timeout=1)
ser2 = serial.Serial(port2, baudrate=115200, timeout=1)
ubr1 = UBXReader(ser1, protfilter=2)
ubr2 = UBXReader(ser2, protfilter=2)


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
                print(f"SV {i}: PRN={prn}, Azimuth={azim}, Elevation={elev}")
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
    if fix == 1:
        print("MON-SPAN data:", mon_span_data)
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
    return base64.b64encode(buf.getvalue()).decode('utf-8')


# background socket
def background_thread():
    timer = 0
    while True:
        try:
            cpu_load = psutil.cpu_percent(interval=0.005)
            timer += 1

            # === Device 1 ===
            _, parsed_data_1 = ubr1.read()
            skyplot_data_1 = ""
            spectrum_data_1 = ""

            if parsed_data_1 and parsed_data_1.identity == "NAV-SAT":
                satellites1 = processData(parsed_data_1)
                buf1 = create_skyplot(satellites1)
                skyplot_data_1 = encode_image(buf1)

            if parsed_data_1 and parsed_data_1.identity == "MON-SPAN":
                mon_span_data_1 = processDataMonSpan(parsed_data_1)
                buf1 = create_spectrum_plot(mon_span_data_1)
                spectrum_data_1 = encode_image(buf1)

            # === Device 2 ===
            _, parsed_data_2 = ubr2.read()
            skyplot_data_2 = ""
            spectrum_data_2 = ""

            if parsed_data_2 and parsed_data_2.identity == "NAV-SAT":
                satellites2 = processData(parsed_data_2)
                buf2 = create_skyplot(satellites2)
                skyplot_data_2 = encode_image(buf2)

            if parsed_data_2 and parsed_data_2.identity == "MON-SPAN":
                mon_span_data_2 = processDataMonSpan(parsed_data_2)
                buf2 = create_spectrum_plot(mon_span_data_2)
                spectrum_data_2 = encode_image(buf2)

            # Send update every 20 loops
            if True:
                timer = 0
                socketio.emit("update_image", {
                    "skyplot1": "data:image/png;base64," + skyplot_data_1,
                    "spectrum1": "data:image/png;base64," + spectrum_data_1,
                    "skyplot2": "data:image/png;base64," + skyplot_data_2,
                    "spectrum2": "data:image/png;base64," + spectrum_data_2,
                    "cpu_load": cpu_load
                })
        except Exception as e:
            print("Error in background thread:", e)



socketio.start_background_task(background_thread)
try:
    logging.debug("Starting Flask app...")
    socketio.run(app, port=5000, allow_unsafe_werkzeug=True)
except KeyboardInterrupt:
    logging.info("Shutting down...")


if __name__ == "__main__":
    socketio.start_background_task(background_thread)
    try:
        logging.debug("Starting Flask app...")
        socketio.run(app, port=5000, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    # finally:
    #     ubx_connector.close_connections()
