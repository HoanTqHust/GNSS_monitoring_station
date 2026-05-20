import queue
import unittest

from thread.ReadSerialThread import ReadSerial
from thread.SocketThread import SocketThread


class RamQueueFlowTests(unittest.TestCase):
    def test_next_event_sequence(self) -> None:
        seq, event1 = ReadSerial._next_event(0, "ubx_frame", {"a": 1})
        self.assertEqual(seq, 1)
        self.assertEqual(event1["seq"], 1)
        self.assertEqual(event1["event_type"], "ubx_frame")

        seq, event2 = ReadSerial._next_event(seq, "epoch_pair", {"b": 2})
        self.assertEqual(seq, 2)
        self.assertEqual(event2["seq"], 2)
        self.assertEqual(event2["event_type"], "epoch_pair")

    def test_put_with_drop_oldest(self) -> None:
        q = queue.Queue(maxsize=1)
        q.put_nowait({"seq": 1})
        metrics, lock = SocketThread.create_metrics()

        SocketThread._put_with_drop_oldest(q, {"seq": 2}, "raw_dropped", metrics, lock)
        newest = q.get_nowait()
        self.assertEqual(newest["seq"], 2)
        self.assertEqual(metrics["raw_dropped"], 1)

    def test_build_queue_stats(self) -> None:
        ingress_q = queue.Queue(maxsize=10)
        detect_q = queue.Queue(maxsize=10)
        raw_q = queue.Queue(maxsize=10)
        ingress_q.put_nowait({"seq": 1})
        detect_q.put_nowait({"seq": 2})
        raw_q.put_nowait({"seq": 3})

        metrics, lock = SocketThread.create_metrics()
        with lock:
            metrics["ingress_received"] = 5
            metrics["last_seq"] = 99
            metrics["detect_processed"] = 4

        stats = SocketThread._build_queue_stats(ingress_q, detect_q, raw_q, metrics, lock)
        self.assertEqual(stats["total_events"], 5)
        self.assertEqual(stats["last_seq"], 99)
        self.assertEqual(stats["last_acked_seq"], 4)
        self.assertEqual(stats["pending_events"], 3)

    def test_enqueue_raw_mqtt_publish_with_drop_oldest(self) -> None:
        mqtt_q = queue.Queue(maxsize=1)
        mqtt_q.put_nowait({"seq": 1})
        metrics, lock = SocketThread.create_metrics()

        SocketThread._enqueue_raw_mqtt_publish(mqtt_q, {"seq": 2}, metrics, lock)
        newest = mqtt_q.get_nowait()
        self.assertEqual(newest["seq"], 2)
        self.assertEqual(metrics["mqtt_raw_queue_dropped"], 1)


if __name__ == "__main__":
    unittest.main()
