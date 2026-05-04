import logging
from multiprocessing import Process
from flask import Flask, render_template
from flask_cors import CORS
from flask_socketio import SocketIO
from thread.ReadSerialThread import ReadSerial
from thread.DurableRawQueue import DurableRawQueue
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
    DurableRawQueue(config.RAW_QUEUE_DB_PATH).close()
    logging.info("Initialized durable raw queue db at %s", config.RAW_QUEUE_DB_PATH)

    serial_process = Process(target=ReadSerial.read_serial, args=(config.RAW_QUEUE_DB_PATH,))

    serial_process.start()

    socketio.start_background_task(
        SocketThread.background_thread,
        config.RAW_QUEUE_DB_PATH,
        socketio,
    )
    try:
        logging.debug("Starting Flask app...")
        socketio.run(app, config.HOSTSOCKET, config.PORTSOCKET, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
