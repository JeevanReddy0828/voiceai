"""SQLite storage for recordings, transcripts, and generated context."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "voiceai.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source      TEXT NOT NULL,              -- 'upload' | 'live'
    created_at  TEXT NOT NULL,
    duration    REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,              -- 'processing' | 'done' | 'error'
    error       TEXT,
    transcript  TEXT,                       -- JSON: list[TranscriptSegment]
    context     TEXT                        -- JSON: MeetingContext
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)


def create_recording(title: str, source: str) -> str:
    rec_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO recordings (id, title, source, created_at, status) VALUES (?, ?, ?, ?, 'processing')",
            (rec_id, title, source, datetime.now(timezone.utc).isoformat()),
        )
    return rec_id


def set_transcript(rec_id: str, segments: list[dict], duration: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE recordings SET transcript = ?, duration = ? WHERE id = ?",
            (json.dumps(segments), duration, rec_id),
        )


def set_context(rec_id: str, context: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE recordings SET context = ?, title = ?, status = 'done' WHERE id = ?",
            (json.dumps(context), context.get("title") or "Untitled", rec_id),
        )


def set_error(rec_id: str, message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE recordings SET status = 'error', error = ? WHERE id = ?",
            (message[:2000], rec_id),
        )


def list_recordings() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, source, created_at, duration, status FROM recordings ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_recording(rec_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    if row is None:
        return None
    rec = dict(row)
    rec["transcript"] = json.loads(rec["transcript"]) if rec["transcript"] else []
    rec["context"] = json.loads(rec["context"]) if rec["context"] else None
    return rec


def delete_recording(rec_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
    return cur.rowcount > 0
