import json
import serial
import threading
import time
import queue
from pyubx2 import UBXReader


class MessageProcessor:
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.running = False
        self.MON_SPAN_1 = queue.Queue()
        self.NAV_SAT_1 = queue.Queue()
        self.MON_SPAN_2 = queue.Queue()
        self.NAV_SAT_2 = queue.Queue()

    def process_messages(self):
        """Continuously process messages from the queue."""
        while self.running:
            try:
                label, raw_data, parsed_data = self.data_queue.get(timeout=1)
                if parsed_data.identity == "MON-SPAN" and label == "ubx2":
                    self.MON_SPAN_2.put((label, raw_data, parsed_data))

                if parsed_data.identity == "NAV-SAT" and label == "ubx2":
                    self.NAV_SAT_2.put((label, raw_data, parsed_data))

                if parsed_data.identity == "MON-SPAN" and label == "ubx1":
                    self.MON_SPAN_1.put((label, raw_data, parsed_data))

                if parsed_data.identity == "NAV-SAT" and label == "ubx1":
                    self.NAV_SAT_1.put((label, raw_data, parsed_data))


                # print(f"[Processing] {label}: {parsed_data} ")
                # Add custom process logic here
            except queue.Empty:
                continue  # No data in queue, keep running

    def start(self):
        """Start the message process loop."""
        self.running = True
        self.processing_thread = threading.Thread(target=self.process_messages, daemon=True)
        self.processing_thread.start()

    def stop(self):
        """Stop the message process loop."""
        self.running = False
        self.processing_thread.join()
