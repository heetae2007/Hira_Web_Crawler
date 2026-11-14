"""SQLite 연결과 RSS 기준점 테이블."""

import sqlite3
from pathlib import Path


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_items (
            item_key TEXT PRIMARY KEY,
            feed_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            published TEXT,
            first_seen_at TEXT NOT NULL,
            notified_at TEXT
        )
        """
    )
    conn.commit()
    return conn
