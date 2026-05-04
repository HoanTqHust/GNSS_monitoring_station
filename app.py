import logging
from multiprocessing import Process
from multiprocessing import Queue as MpQueue
from queue import Queue as ThreadQueue
from flask import Flask, render_template
from flask_cors import CORS
from flask_socketio import SocketIO
from thread.ReadSerialThread import ReadSerial
from thread.SocketThread import SocketThread
from config import config
# config


logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@socketio.on('connect')
def handle_connect():
    print("Client connected")


if __name__ == "__main__":
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
        socketio.run(app, config.HOSTSOCKET, config.PORTSOCKET, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
