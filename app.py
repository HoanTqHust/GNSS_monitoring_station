import json
import logging
import time
from flask import Flask, render_template, jsonify

from connect.connect import UBXConnector
from process.process import MessageProcessor

fix=1
# Setup logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Load config
with open("config.json", "r") as file:
    config = json.load(file)

# Initialize UBXConnector
ubx_connector = UBXConnector(config)
ubx_connector.start()  # Start the UBX connector in a background thread
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
            # Uncomment the following line for debugging:
            # print("Updated satellites:", satellites)
            time.sleep(1)
    except Exception as e:
        print("Error reading UBX data:", e)
    return satellites

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
        label, raw_data, parsed_data= ubx_processor.MON_SPAN_1.get(timeout=5)
        

    while not ubx_processor.NAV_SAT_1.empty():
        label, raw_data, parsed_data= ubx_processor.NAV_SAT_1.get(timeout=5)
        nav_sat_datas.append(processData(parsed_data))
        

    while not ubx_processor.MON_SPAN_2.empty():
        label, raw_data, parsed_data= ubx_processor.MON_SPAN_2.get(timeout=5)
        

    while not ubx_processor.NAV_SAT_2.empty():
        label, raw_data, parsed_data= ubx_processor.NAV_SAT_2.get(timeout=5)
        #processData(parsed_data)
        

    return jsonify({"mon_span": mon_span_datas, "nav_sat": nav_sat_datas})


if __name__ == "__main__":
    try:
        logging.debug("Starting Flask app...")
        app.run(debug=True, use_reloader=False)  # Prevent multiple threads due to auto-reloader
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        ubx_connector.stop()  # Ensure cleanup on exit
