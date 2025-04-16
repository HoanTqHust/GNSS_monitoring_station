
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
from UbloxChart import UbloxChart
import threading

# config
with open("config.json", "r") as file:
    config = json.load(file)
fix = config.get("fix", 0)
BUFFER_SAMPLES = config.get("BUFFER_SAMPLES", 0)
PLOT_INTERVAL = config.get("PLOT_INTERVAL", 0)
port1 = config.get("port1", "")
port2 = config.get("port2", "")
hostsocket = config.get("hostsocket", "0.0.0.0")
portsocket = config.get("portsocket", 5000)

logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
data_queue = Queue(maxsize=1000)    

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



# ---------- Helper Functions ----------
def append_with_limit(queue, item, maxlen=BUFFER_SAMPLES):
    queue.append(item)
    if len(queue) > maxlen:
        del queue[0]

def read_serial():
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
    chart = UbloxChart()
    last_plot_time = time.time()
    while True:
        try:
            # Plot if enough time passed and buffer is full
            current_time = time.time()
            dps_plot = ""
            cpu_load = psutil.cpu_percent(interval=0.5)
            combined_samples, skyplot_data_1, skyplot_data_2, spectrum_data_1, spectrum_data_2 = data_queue.get()
            if current_time - last_plot_time >= PLOT_INTERVAL:
                last_plot_time = current_time
                dps_plot = UbloxChart.raw2ImageDps(dps_plot_data)
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
                
                skyplot_1 = UbloxChart.raw2ImageSkyplot(skyplot_data_1)
                skyplot_2 = UbloxChart.raw2ImageSkyplot(skyplot_data_2)
                spectrum_1 = UbloxChart.raw2ImageSpectrum(spectrum_data_1)
                spectrum_2 = UbloxChart.raw2ImageSpectrum(spectrum_data_2)
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
        socketio.run(app, hostsocket, portsocket, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
