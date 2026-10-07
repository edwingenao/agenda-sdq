"""SQLite: eventos + caché de páginas (para no reprocesar lo que no cambió)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  key          TEXT PRIMARY KEY,
  source       TEXT NOT NULL,
  url          TEXT NOT NULL,
  start_date   TEXT NOT NULL,
  end_date     TEXT NOT NULL,
  payload      TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  first_seen   TEXT NOT NULL,
  last_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_end ON events(end_date);
CREATE TABLE IF NOT EXISTS pages (
  url          TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  fetched_at   TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- páginas ---
    def page_known(self, url: str) -> bool:
        return self.conn.execute("SELECT 1 FROM pages WHERE url=?", (url,)).fetchone() is not None

    def page_changed(self, url: str, fingerprint: str) -> bool:
        row = self.conn.execute("SELECT content_hash FROM pages WHERE url=?", (url,)).fetchone()
        return row is None or row["content_hash"] != fingerprint

    def record_page(self, url: str, fingerprint: str, now: str) -> None:
        self.conn.execute(
            "INSERT INTO pages(url, content_hash, fetched_at) VALUES(?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET content_hash=excluded.content_hash, fetched_at=excluded.fetched_at",
            (url, fingerprint, now),
        )
        self.conn.commit()

    def touch_url(self, url: str, now: str) -> None:
        self.conn.execute("UPDATE events SET last_seen=? WHERE url=?", (now, url))
        self.conn.execute("UPDATE pages SET fetched_at=? WHERE url=?", (now, url))
        self.conn.commit()

    # --- eventos ---
    def upsert_event(self, ev, now: str) -> str:
        """Devuelve 'new' | 'updated' | 'same'."""
        h = ev.content_hash()
        row = self.conn.execute("SELECT content_hash FROM events WHERE key=?", (ev.key,)).fetchone()
        payload = json.dumps(ev.to_dict(), ensure_ascii=False)
        if row is None:
            self.conn.execute(
                "INSERT INTO events(key, source, url, start_date, end_date, payload, content_hash, needs_review, "
                "first_seen, last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ev.key, ev.source, ev.url, ev.start, ev.end, payload, h, int(ev.needs_review), now, now),
            )
            status = "new"
        elif row["content_hash"] != h:
            self.conn.execute(
                "UPDATE events SET start_date=?, end_date=?, payload=?, content_hash=?, needs_review=?, last_seen=? "
                "WHERE key=?",
                (ev.start, ev.end, payload, h, int(ev.needs_review), now, ev.key),
            )
            status = "updated"
        else:
            self.conn.execute("UPDATE events SET last_seen=? WHERE key=?", (now, ev.key))
            status = "same"
        self.conn.commit()
        return status

    def upcoming(self, today: date) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM events WHERE end_date >= ? ORDER BY start_date, key", (today.isoformat(),)
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def review_queue(self, today: date) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM events WHERE needs_review=1 AND end_date >= ? ORDER BY start_date",
            (today.isoformat(),),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]
