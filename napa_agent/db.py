from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _to_sqlite_path(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)
    if database_url == "sqlite:///:memory:" or database_url == "sqlite+pysqlite:///:memory:":
        return ":memory:"
    return database_url


def get_engine(database_url: str) -> sqlite3.Connection:
    path = _to_sqlite_path(database_url)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            payload TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            UNIQUE(source, item_id)
        )
        """
    )
    conn.commit()


def insert_observation(
    conn: sqlite3.Connection,
    *,
    source: str,
    item_id: str,
    title: str,
    url: str,
    payload: dict[str, Any],
    observed_at: datetime | None = None,
) -> bool:
    observed_at = observed_at or datetime.now(timezone.utc)
    cur = conn.execute(
        "SELECT id FROM observations WHERE source = ? AND item_id = ?",
        (source, item_id),
    )
    if cur.fetchone() is not None:
        return False

    conn.execute(
        """
        INSERT INTO observations (source, item_id, title, url, payload, observed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source, item_id, title, url, json.dumps(payload), observed_at.isoformat()),
    )
    conn.commit()
    return True


def fetch_recent(conn: sqlite3.Connection, source: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT source, item_id, title, url, payload, observed_at
        FROM observations
        WHERE source = ?
        ORDER BY observed_at DESC
        LIMIT ?
        """,
        (source, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "source": row["source"],
                "item_id": row["item_id"],
                "title": row["title"],
                "url": row["url"],
                "payload": json.loads(row["payload"]),
                "observed_at": datetime.fromisoformat(row["observed_at"]),
            }
        )
    return result
