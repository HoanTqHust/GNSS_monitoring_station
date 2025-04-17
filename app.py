import logging
from multiprocessing import Process
from multiprocessing import Queue
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
data_queue = Queue(maxsize=1000)  
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

    serial_process = Process(target=ReadSerial.read_serial, args=(data_queue,))     

    serial_process.start()

    socketio.start_background_task(SocketThread.background_thread, data_queue, socketio)
    try:
        logging.debug("Starting Flask app...")
        socketio.run(app, config.HOSTSOCKET, config.PORTSOCKET, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
