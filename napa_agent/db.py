from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from napa_agent.sources.napatech_shareinfo import ShareholderRow, ShareholderSnapshot


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholder_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_dt TEXT NOT NULL,
            updated_label TEXT,
            source_url TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholder_rows (
            snapshot_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            holder_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            pct REAL NOT NULL,
            holder_type TEXT,
            country TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES shareholder_snapshots(snapshot_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholder_runs (
            run_dt TEXT NOT NULL,
            attempt_hour INTEGER NOT NULL,
            updated_changed_bool INTEGER NOT NULL,
            notes TEXT
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


def insert_shareholder_snapshot(
    conn: sqlite3.Connection,
    snapshot: ShareholderSnapshot,
    *,
    attempt_hour: int,
    notes: str | None = None,
) -> tuple[bool, int | None]:
    last_snapshot = _fetch_last_snapshot(conn)
    new_hash = _rows_hash(snapshot.rows)

    is_changed = True
    if last_snapshot is not None:
        last_updated, last_hash = last_snapshot
        if (snapshot.updated_label or "") == (last_updated or "") and new_hash == last_hash:
            is_changed = False

    snapshot_id: int | None = None
    if is_changed:
        cursor = conn.execute(
            """
            INSERT INTO shareholder_snapshots (snapshot_dt, updated_label, source_url)
            VALUES (?, ?, ?)
            """,
            (snapshot.fetched_at.isoformat(), snapshot.updated_label, snapshot.source_url),
        )
        snapshot_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO shareholder_rows (
                snapshot_id, rank, holder_name, shares, pct, holder_type, country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    row.rank,
                    row.holder_name,
                    row.shares,
                    row.pct,
                    row.holder_type,
                    row.country,
                )
                for row in snapshot.rows
            ],
        )

    conn.execute(
        """
        INSERT INTO shareholder_runs (run_dt, attempt_hour, updated_changed_bool, notes)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            attempt_hour,
            1 if is_changed else 0,
            notes,
        ),
    )
    conn.commit()
    return is_changed, snapshot_id


def insert_shareholder_run(
    conn: sqlite3.Connection,
    *,
    attempt_hour: int,
    updated_changed_bool: bool,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO shareholder_runs (run_dt, attempt_hour, updated_changed_bool, notes)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            attempt_hour,
            1 if updated_changed_bool else 0,
            notes,
        ),
    )
    conn.commit()


def fetch_latest_shareholder_snapshot(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT snapshot_id, snapshot_dt, updated_label, source_url
        FROM shareholder_snapshots
        ORDER BY snapshot_dt DESC, snapshot_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(conn, row)


def fetch_shareholder_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT snapshot_id, snapshot_dt, updated_label, source_url
        FROM shareholder_snapshots
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(conn, row)


def fetch_snapshot_nearest_to(conn: sqlite3.Connection, target_dt: datetime) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT snapshot_id, snapshot_dt, updated_label, source_url
        FROM shareholder_snapshots
        ORDER BY ABS(strftime('%s', snapshot_dt) - strftime('%s', ?)) ASC, snapshot_dt DESC
        LIMIT 1
        """,
        (target_dt.isoformat(),),
    ).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(conn, row)


def _fetch_last_snapshot(conn: sqlite3.Connection) -> tuple[str | None, str] | None:
    snapshot = conn.execute(
        """
        SELECT snapshot_id, updated_label
        FROM shareholder_snapshots
        ORDER BY snapshot_dt DESC, snapshot_id DESC
        LIMIT 1
        """
    ).fetchone()
    if snapshot is None:
        return None

    rows = conn.execute(
        """
        SELECT rank, holder_name, shares, pct, holder_type, country
        FROM shareholder_rows
        WHERE snapshot_id = ?
        ORDER BY rank ASC
        """,
        (snapshot["snapshot_id"],),
    ).fetchall()

    serialized_rows = [
        {
            "rank": row["rank"],
            "holder_name": row["holder_name"],
            "shares": row["shares"],
            "pct": row["pct"],
            "holder_type": row["holder_type"],
            "country": row["country"],
        }
        for row in rows
    ]
    return snapshot["updated_label"], _hash_serialized(serialized_rows)


def _row_to_snapshot(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    holder_rows = conn.execute(
        """
        SELECT rank, holder_name, shares, pct, holder_type, country
        FROM shareholder_rows
        WHERE snapshot_id = ?
        ORDER BY rank ASC
        """,
        (row["snapshot_id"],),
    ).fetchall()
    return {
        "snapshot_id": row["snapshot_id"],
        "snapshot_dt": datetime.fromisoformat(row["snapshot_dt"]),
        "updated_label": row["updated_label"],
        "source_url": row["source_url"],
        "rows": [
            {
                "rank": holder_row["rank"],
                "holder_name": holder_row["holder_name"],
                "shares": holder_row["shares"],
                "pct": holder_row["pct"],
                "holder_type": holder_row["holder_type"],
                "country": holder_row["country"],
            }
            for holder_row in holder_rows
        ],
    }


def _rows_hash(rows: list[ShareholderRow]) -> str:
    serialized_rows = [row.model_dump() for row in sorted(rows, key=lambda item: item.rank)]
    return _hash_serialized(serialized_rows)


def _hash_serialized(payload: list[dict[str, Any]]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
