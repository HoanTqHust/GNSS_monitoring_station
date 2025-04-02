import json
import logging
import time
import io
import numpy as np
import matplotlib.pyplot as plt
import matplotlib

from flask import Flask, render_template, jsonify, send_file

from connect.connect import UBXConnector
from process.process import MessageProcessor

matplotlib.use('Agg')
# use fix to fix
fix = 1
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

with open("config.json", "r") as file:
    config = json.load(file)

ubx_connector = UBXConnector(config)
ubx_connector.start()
ubx_processor = MessageProcessor(ubx_connector.data_queue)
ubx_processor.start()


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


def create_skyplot(satellites):
    """Create a skyplot PNG image from the current satellite data."""
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, polar=True)

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
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/data")
def get_data():
    """Lấy dữ liệu mới nhất từ hai queue."""
    mon_span_datas = []
    nav_sat_datas = []

    while not ubx_processor.MON_SPAN_1.empty():
        label, raw_data, parsed_data = ubx_processor.MON_SPAN_1.get(timeout=5)

    while not ubx_processor.NAV_SAT_1.empty():
        label, raw_data, parsed_data = ubx_processor.NAV_SAT_1.get(timeout=5)
        nav_sat_datas.append(processData(parsed_data))

    while not ubx_processor.MON_SPAN_2.empty():
        label, raw_data, parsed_data = ubx_processor.MON_SPAN_2.get(timeout=5)

    while not ubx_processor.NAV_SAT_2.empty():
        label, raw_data, parsed_data = ubx_processor.NAV_SAT_2.get(timeout=5)
        # processData(parsed_data)

    return jsonify({"mon_span": mon_span_datas, "nav_sat": nav_sat_datas})


@app.route("/skyplot")
def skyplot():
    """Return a skyplot PNG image created from the current satellite data."""
    satellites = []
    while not ubx_processor.NAV_SAT_1.empty():
        label, raw_data, parsed_data = ubx_processor.NAV_SAT_1.get(timeout=5)
        satellites.extend(processData(parsed_data))
    # haven't processed NAV-SAT_2 yet
    # while not ubx_processor.NAV_SAT_2.empty():
    #     label, raw_data, parsed_data = ubx_processor.NAV_SAT_2.get(timeout=5)
    #     satellites.extend(processData(parsed_data))

    buf = create_skyplot(satellites)
    return send_file(buf, mimetype='image/png')


if __name__ == "__main__":
    try:
        logging.debug("Starting Flask app...")
        app.run(debug=True, use_reloader=False)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        ubx_connector.stop()