import json
import logging
from flask import Flask, render_template, jsonify

from connect.connect import UBXConnector
from process.process import MessageProcessor

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
        print(parsed_data)

    while not ubx_processor.NAV_SAT_1.empty():
        label, raw_data, parsed_data= ubx_processor.NAV_SAT_1.get(timeout=5)
        print(parsed_data)

    while not ubx_processor.MON_SPAN_2.empty():
        label, raw_data, parsed_data= ubx_processor.MON_SPAN_2.get(timeout=5)
        print(parsed_data)

    while not ubx_processor.NAV_SAT_2.empty():
        label, raw_data, parsed_data= ubx_processor.NAV_SAT_2.get(timeout=5)
        print(parsed_data)

    return jsonify({"mon_span": mon_span_datas, "nav_sat": nav_sat_datas})


if __name__ == "__main__":
    try:
        logging.debug("Starting Flask app...")
        app.run(debug=True, use_reloader=False)  # Prevent multiple threads due to auto-reloader
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        ubx_connector.stop()  # Ensure cleanup on exit
