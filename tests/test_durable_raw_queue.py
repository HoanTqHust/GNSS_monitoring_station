import tempfile
import unittest
from pathlib import Path

from thread.DurableRawQueue import DurableRawQueue


class DurableRawQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "raw_bus.sqlite3")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_ack_persists_across_reopen(self) -> None:
        queue = DurableRawQueue(self.db_path)
        queue.enqueue("ubx_frame", {"value": 1})
        queue.enqueue("ubx_frame", {"value": 2})
        queue.enqueue("ubx_frame", {"value": 3})

        batch = queue.get_pending_batch("consumer_a", 2)
        self.assertEqual([record.payload["value"] for record in batch], [1, 2])
        queue.ack("consumer_a", batch[-1].seq)
        queue.close()

        reopened = DurableRawQueue(self.db_path)
        second_batch = reopened.get_pending_batch("consumer_a", 10)
        self.assertEqual([record.payload["value"] for record in second_batch], [3])
        reopened.close()

    def test_unacked_message_is_replayed(self) -> None:
        queue = DurableRawQueue(self.db_path)
        seq = queue.enqueue("ubx_frame", {"value": 99})

        first_read = queue.get_pending_batch("consumer_retry", 1)
        self.assertEqual(len(first_read), 1)
        self.assertEqual(first_read[0].seq, seq)
        queue.close()

        reopened = DurableRawQueue(self.db_path)
        second_read = reopened.get_pending_batch("consumer_retry", 1)
        self.assertEqual(len(second_read), 1)
        self.assertEqual(second_read[0].seq, seq)
        reopened.close()

    def test_consumers_have_independent_offsets(self) -> None:
        queue = DurableRawQueue(self.db_path)
        queue.enqueue_many(
            [
                ("ubx_frame", {"value": "a"}),
                ("ubx_frame", {"value": "b"}),
            ]
        )

        consumer_a_batch = queue.get_pending_batch("consumer_a", 1)
        self.assertEqual([record.payload["value"] for record in consumer_a_batch], ["a"])
        queue.ack("consumer_a", consumer_a_batch[-1].seq)

        consumer_b_batch = queue.get_pending_batch("consumer_b", 10)
        self.assertEqual([record.payload["value"] for record in consumer_b_batch], ["a", "b"])
        queue.close()


if __name__ == "__main__":
    unittest.main()
