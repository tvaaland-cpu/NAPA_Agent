from datetime import datetime, timezone

from napa_agent.db import get_engine, init_db, insert_observation, insert_shareholder_snapshot
from napa_agent.sources.napatech_shareinfo import ShareholderRow, ShareholderSnapshot


def test_insert_observation_dedup() -> None:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    first = insert_observation(
        engine,
        source="euronext_news",
        item_id="abc123",
        title="First item",
        url="https://example.com/1",
        payload={"id": "abc123"},
    )
    second = insert_observation(
        engine,
        source="euronext_news",
        item_id="abc123",
        title="First item duplicate",
        url="https://example.com/1",
        payload={"id": "abc123"},
    )

    assert first is True
    assert second is False


def test_insert_shareholder_snapshot_dedup() -> None:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    rows = [
        ShareholderRow(rank=1, holder_name="A", shares=1000, pct=10.0),
        ShareholderRow(rank=2, holder_name="B", shares=900, pct=9.0),
    ]
    snapshot = ShareholderSnapshot(
        updated_label="Updated January 9. 2025",
        fetched_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        rows=rows,
        source_url="https://www.napatech.com/investor-relations/share-information/",
    )

    changed_first, snapshot_id_first = insert_shareholder_snapshot(engine, snapshot, attempt_hour=10)
    changed_second, snapshot_id_second = insert_shareholder_snapshot(engine, snapshot, attempt_hour=11)

    assert changed_first is True
    assert snapshot_id_first is not None
    assert changed_second is False
    assert snapshot_id_second is None

    run_rows = engine.execute("SELECT COUNT(*) AS cnt FROM shareholder_runs").fetchone()
    snap_rows = engine.execute("SELECT COUNT(*) AS cnt FROM shareholder_snapshots").fetchone()
    holder_rows = engine.execute("SELECT COUNT(*) AS cnt FROM shareholder_rows").fetchone()

    assert run_rows["cnt"] == 2
    assert snap_rows["cnt"] == 1
    assert holder_rows["cnt"] == 2
