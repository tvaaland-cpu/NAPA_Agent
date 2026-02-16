from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from napa_agent.sources.napatech_shareinfo import ShareholderRow, ShareholderSnapshot

RUMOR_STATUSES = {"new", "watch", "confirmed", "debunked", "stale"}


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
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT,
            discovered_at TEXT NOT NULL,
            source_tier INTEGER NOT NULL,
            tags_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            rumor INTEGER NOT NULL DEFAULT 0,
            UNIQUE(url),
            UNIQUE(content_hash)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rumors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_item_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(news_item_id) REFERENCES news_items(id)
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


def _build_content_hash(url: str, title: str, summary: str) -> str:
    del url
    normalized = f"{title.strip()}\n{summary.strip()}".lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def insert_news_item(
    conn: sqlite3.Connection,
    *,
    url: str,
    title: str,
    published_at: datetime | None,
    discovered_at: datetime | None,
    source_tier: int,
    tags: list[str],
    summary: str,
    rumor: bool,
) -> tuple[bool, int | None]:
    content_hash = _build_content_hash(url=url, title=title, summary=summary)
    discovered_at = discovered_at or datetime.now(timezone.utc)

    existing = conn.execute(
        "SELECT id FROM news_items WHERE url = ? OR content_hash = ?",
        (url, content_hash),
    ).fetchone()
    if existing is not None:
        return False, None

    cursor = conn.execute(
        """
        INSERT INTO news_items (
            url, title, published_at, discovered_at, source_tier,
            tags_json, summary, content_hash, rumor
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            title,
            published_at.isoformat() if published_at else None,
            discovered_at.isoformat(),
            source_tier,
            json.dumps(tags),
            summary,
            content_hash,
            1 if rumor else 0,
        ),
    )
    item_id = int(cursor.lastrowid)

    if rumor:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO rumors (news_item_id, status, created_at, updated_at)
            VALUES (?, 'new', ?, ?)
            """,
            (item_id, now, now),
        )

    conn.commit()
    return True, item_id


def set_rumor_status(conn: sqlite3.Connection, rumor_id: int, status: str) -> None:
    if status not in RUMOR_STATUSES:
        raise ValueError(f"Invalid rumor status: {status}")

    conn.execute(
        "UPDATE rumors SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), rumor_id),
    )
    conn.commit()


def confirm_rumors_with_tier1_item(conn: sqlite3.Connection, tier1_news_item_id: int) -> int:
    row = conn.execute(
        "SELECT title FROM news_items WHERE id = ? AND source_tier = 1",
        (tier1_news_item_id,),
    ).fetchone()
    if row is None:
        return 0

    tier1_tokens = {token.lower() for token in row["title"].split() if len(token) > 4}
    if not tier1_tokens:
        return 0

    rumor_rows = conn.execute(
        """
        SELECT r.id, n.title
        FROM rumors r
        JOIN news_items n ON n.id = r.news_item_id
        WHERE r.status IN ('new', 'watch', 'stale')
        """
    ).fetchall()

    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for rumor in rumor_rows:
        rumor_tokens = {token.lower() for token in rumor["title"].split() if len(token) > 4}
        if tier1_tokens.intersection(rumor_tokens):
            conn.execute(
                "UPDATE rumors SET status = 'confirmed', updated_at = ? WHERE id = ?",
                (now, rumor["id"]),
            )
            updated += 1

    if updated:
        conn.commit()
    return updated


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
