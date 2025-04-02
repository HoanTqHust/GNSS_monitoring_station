import serial
import threading
import time
import queue
from pyubx2 import UBXReader

# Receiver

class UBXConnector:
    def __init__(self, config):
        self.config = config
        self.devices = {}
        self.running = False
        self.data_queue = queue.Queue()  # Queue for inter-thread communication
        # self.processor = MessageProcessor(self.data_queue)

    def connect_ubx(self, label, port):
        """Establish a connection to a UBX device."""
        try:
            ser = serial.Serial(port, baudrate=115200, timeout=1)
            ubr = UBXReader(ser, protfilter=2)  # UBX protocol only
            self.devices[label] = (ser, ubr)
            print(f"Connected to {label} on {port}")
        except Exception as e:
            print(f"Failed to connect to {label} on {port}: {e}")
            self.devices[label] = (None, None)

    def read_messages(self):
        """Continuously read and enqueue messages from all connected devices."""
        while self.running:
            for label in list(self.devices.keys()):
                self.read_message(label)
            time.sleep(0.1)

    def read_message(self, label):
        """Read a single UBX message from a specific device and enqueue it."""
        ser, ubr = self.devices.get(label, (None, None))
        if ubr and ser:
            try:
                data = next(ubr, None)
                if data:
                    raw_data, parsed_data = data
                    self.data_queue.put((label, raw_data, parsed_data))  # Send data to process thread
            except Exception as e:
                print(f"Error reading from {label}: {e}")

    def close_connections(self):
        """Close all UBX device connections."""
        for label, (ser, _) in self.devices.items():
            if ser:
                ser.close()
                print(f"Closed connection to {label}")
        self.devices.clear()

    def start(self):
        """Initialize connections and start reading & process threads."""
        self.running = True
        for label, port in self.config.items():
            self.connect_ubx(label, port)

        self.reading_thread = threading.Thread(target=self.read_messages, daemon=True)
        self.reading_thread.start()

        # self.processor.start()

    def stop(self):
        """Stop threads and close connections."""
        self.running = False
        self.reading_thread.join()
        # self.processor.stop()
        self.close_connections()
