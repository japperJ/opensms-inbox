"""SQLite storage for the OpenSMS inbox."""

import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id TEXT UNIQUE,
    event TEXT NOT NULL,
    sender TEXT,
    body TEXT,
    parts INTEGER,
    sim TEXT,
    received_at TEXT,
    sent_at TEXT,
    raw TEXT NOT NULL,
    stored_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_received
    ON messages(received_at DESC, id DESC);
"""

SMS_EVENT = "sms.received"
TEST_EVENT = "webhook.test"


def connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: str):
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_message(db_path: str, payload: dict, raw_body: bytes) -> tuple:
    """Store one webhook payload. Returns (inserted, row_id).

    A repeated delivery_id is ignored, so the sender's at-least-once
    retries stay idempotent.
    """
    sim = payload.get("sim")
    values = (
        payload.get("delivery_id"),
        str(payload.get("event")),
        payload.get("from"),
        payload.get("text"),
        payload.get("parts"),
        json.dumps(sim, ensure_ascii=False) if isinstance(sim, dict) else None,
        payload.get("received_at"),
        payload.get("sent_at"),
        raw_body.decode("utf-8", errors="replace"),
        _utc_now(),
    )
    try:
        with connect(db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    delivery_id, event, sender, body, parts, sim,
                    received_at, sent_at, raw, stored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return True, cursor.lastrowid
    except sqlite3.IntegrityError:
        return False, None


def list_messages(db_path: str, query: str = "", limit: int = 50,
                  offset: int = 0) -> tuple:
    where = ""
    params = []
    if query:
        where = "WHERE sender LIKE ? OR body LIKE ?"
        like = f"%{query}%"
        params = [like, like]
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM messages {where}
            ORDER BY COALESCE(received_at, stored_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        total = connection.execute(
            f"SELECT COUNT(*) FROM messages {where}", params
        ).fetchone()[0]
    return [dict(row) for row in rows], total


def get_message(db_path: str, message_id: int) -> dict | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_message(db_path: str, message_id: int) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM messages WHERE id = ?", (message_id,)
        )
        return cursor.rowcount > 0
