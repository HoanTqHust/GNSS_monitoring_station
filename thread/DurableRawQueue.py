from __future__ import annotations

import os
import pickle
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class DurableQueueRecord:
    seq: int
    topic: str
    created_at_utc: str
    payload: Any


class DurableRawQueue:
    """SQLite-backed append-only queue with per-consumer ACK offsets."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent_dir, exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=FULL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    payload_blob BLOB NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consumer_offsets (
                    consumer_id TEXT PRIMARY KEY,
                    last_acked_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at_utc TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_raw_events_topic_seq
                ON raw_events(topic, seq);
                """
            )

    def close(self) -> None:
        self._conn.close()

    def register_consumer(self, consumer_id: str) -> None:
        if not consumer_id:
            raise ValueError("consumer_id must not be empty")
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consumer_offsets (consumer_id, last_acked_seq, updated_at_utc)
                VALUES (?, 0, ?)
                ON CONFLICT(consumer_id) DO NOTHING;
                """,
                (consumer_id, now),
            )

    def _serialize_payload(self, payload: Any) -> bytes:
        return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)

    def _deserialize_payload(self, payload_blob: bytes) -> Any:
        return pickle.loads(payload_blob)

    def enqueue(self, topic: str, payload: Any) -> int:
        return self.enqueue_many([(topic, payload)])

    def enqueue_many(self, items: list[tuple[str, Any]]) -> int:
        if not items:
            raise ValueError("items must not be empty")

        now = _utc_now_iso()
        last_seq = 0
        with self._conn:
            cursor = self._conn.cursor()
            for topic, payload in items:
                if not topic:
                    raise ValueError("topic must not be empty")
                payload_blob = self._serialize_payload(payload)
                cursor.execute(
                    """
                    INSERT INTO raw_events(topic, created_at_utc, payload_blob)
                    VALUES (?, ?, ?);
                    """,
                    (topic, now, payload_blob),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("failed to get inserted sequence id")
                last_seq = int(cursor.lastrowid)
        return last_seq

    def get_last_acked_seq(self, consumer_id: str) -> int:
        self.register_consumer(consumer_id)
        row = self._conn.execute(
            "SELECT last_acked_seq FROM consumer_offsets WHERE consumer_id = ?;",
            (consumer_id,),
        ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def get_pending_batch(self, consumer_id: str, limit: int) -> list[DurableQueueRecord]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        last_acked_seq = self.get_last_acked_seq(consumer_id)
        rows = self._conn.execute(
            """
            SELECT seq, topic, created_at_utc, payload_blob
            FROM raw_events
            WHERE seq > ?
            ORDER BY seq ASC
            LIMIT ?;
            """,
            (last_acked_seq, limit),
        ).fetchall()
        records: list[DurableQueueRecord] = []
        for seq, topic, created_at_utc, payload_blob in rows:
            records.append(
                DurableQueueRecord(
                    seq=int(seq),
                    topic=str(topic),
                    created_at_utc=str(created_at_utc),
                    payload=self._deserialize_payload(payload_blob),
                )
            )
        return records

    def ack(self, consumer_id: str, seq: int) -> None:
        if seq <= 0:
            raise ValueError("seq must be > 0")
        self.register_consumer(consumer_id)
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                UPDATE consumer_offsets
                SET last_acked_seq = CASE
                    WHEN last_acked_seq < ? THEN ?
                    ELSE last_acked_seq
                END,
                updated_at_utc = ?
                WHERE consumer_id = ?;
                """,
                (seq, seq, now, consumer_id),
            )

    def get_stats(self, consumer_id: str | None = None) -> dict[str, int]:
        total_events = int(
            self._conn.execute("SELECT COUNT(*) FROM raw_events;").fetchone()[0]
        )
        last_seq_row = self._conn.execute("SELECT MAX(seq) FROM raw_events;").fetchone()
        last_seq = int(last_seq_row[0]) if last_seq_row and last_seq_row[0] is not None else 0
        stats = {
            "total_events": total_events,
            "last_seq": last_seq,
        }
        if consumer_id is None:
            return stats
        last_acked = self.get_last_acked_seq(consumer_id)
        stats["last_acked_seq"] = last_acked
        stats["pending_events"] = max(0, last_seq - last_acked)
        return stats
