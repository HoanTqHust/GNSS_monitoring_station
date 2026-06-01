import logging
import os
from multiprocessing import Process
from multiprocessing import Queue as MpQueue
from queue import Queue as ThreadQueue
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO
from thread.ReadSerialThread import ReadSerial
from thread.SocketThread import SocketThread
from thread.SDRThread import SDRThread
from config import config
# config


class _MqttLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        logger_name = (record.name or "").lower()
        if logger_name.startswith("telemetry.mqtt_publisher"):
            return True
        if "mqtt" in logger_name:
            return True
        message = record.getMessage().lower()
        return "mqtt" in message


def _setup_logging() -> str:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    all_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all.log")
    mqtt_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mqtt.log")
    root_logger = logging.getLogger()
    existing_all_handler = any(
        isinstance(handler, logging.FileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == all_log_path
        for handler in root_logger.handlers
    )
    if not existing_all_handler:
        all_handler = logging.FileHandler(all_log_path, encoding="utf-8")
        all_handler.setLevel(logging.DEBUG)
        all_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root_logger.addHandler(all_handler)

    existing_handler = any(
        isinstance(handler, logging.FileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == mqtt_log_path
        for handler in root_logger.handlers
    )
    if not existing_handler:
        mqtt_handler = logging.FileHandler(mqtt_log_path, encoding="utf-8")
        mqtt_handler.setLevel(logging.DEBUG)
        mqtt_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        mqtt_handler.addFilter(_MqttLogFilter())
        root_logger.addHandler(mqtt_handler)
    return all_log_path


ALL_LOG_PATH = _setup_logging()
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/sdr")
def sdr():
    return render_template("sdr.html")


@app.route("/sdr/latest_bmp")
def sdr_latest_bmp():
    bmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BKDATASET")
    if not os.path.isdir(bmp_dir):
        return jsonify({"filename": None})
    files = [os.path.join(bmp_dir, f) for f in os.listdir(bmp_dir) if f.lower().endswith(".bmp")]
    if not files:
        return jsonify({"filename": None})
    latest = max(files, key=os.path.getmtime)
    return jsonify({"filename": latest})


@app.route("/sdr/bmp/<path:filename>")
def sdr_serve_bmp(filename):
    """Serve BMP file from BKDATASET directory"""
    bmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BKDATASET")
    # Security: only allow files within BKDATASET
    if ".." in filename or not filename.endswith(".bmp"):
        return "Invalid file", 400
    full_path = os.path.join(bmp_dir, os.path.basename(filename))
    if not os.path.exists(full_path):
        return "Not found", 404
    return send_file(full_path, mimetype="image/bmp")


@app.route("/sdr/stop", methods=["POST"])
def sdr_stop():
    sdr_thread = SDRThread.get_instance(socketio)
    sdr_thread.stop()
    socketio.emit("sdr_stopped")
    return jsonify({"status": "stopped"})


@socketio.on('connect')
def handle_connect():
    print("Client connected")


if __name__ == "__main__":
    logging.info("Full file logging enabled path=%s", ALL_LOG_PATH)
    logging.info(
        "MQTT runtime config enabled=%s host=%s port=%s username=%s password_set=%s",
        config.MQTT_ENABLED,
        config.MQTT_HOST,
        config.MQTT_PORT,
        config.MQTT_USERNAME,
        bool(config.MQTT_PASSWORD),
    )

    ingress_queue = MpQueue(maxsize=config.RAM_INGRESS_QUEUE_SIZE)
    detect_queue = ThreadQueue(maxsize=config.RAM_DETECT_QUEUE_SIZE)
    raw_queue = ThreadQueue(maxsize=config.RAM_RAW_QUEUE_SIZE)
    metrics, metrics_lock = SocketThread.create_metrics()
    logging.info(
        "Initialized RAM queues ingress=%s detect=%s raw=%s",
        config.RAM_INGRESS_QUEUE_SIZE,
        config.RAM_DETECT_QUEUE_SIZE,
        config.RAM_RAW_QUEUE_SIZE,
    )

    serial_process = Process(target=ReadSerial.read_serial, args=(ingress_queue,))

    serial_process.start()

    socketio.start_background_task(
        SocketThread.router_thread,
        ingress_queue,
        detect_queue,
        raw_queue,
        metrics,
        metrics_lock,
    )
    socketio.start_background_task(
        SocketThread.detect_consumer_thread,
        detect_queue,
        socketio,
        metrics,
        metrics_lock,
    )
    socketio.start_background_task(
        SocketThread.raw_consumer_thread,
        ingress_queue,
        detect_queue,
        raw_queue,
        socketio,
        metrics,
        metrics_lock,
    )
    try:
        logging.debug("Starting Flask app...")

        # Start SDR thread if enabled
        if config.SDR_ENABLED:
            sdr_thread = SDRThread.get_instance(socketio)
            sdr_thread.start()
            logging.info("SDR thread started")

        socketio.run(app, config.HOSTSOCKET, config.PORTSOCKET, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
