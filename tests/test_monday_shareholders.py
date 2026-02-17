from datetime import datetime

import pytest

from napa_agent import db
from napa_agent.pipelines import shareholders as module
from napa_agent.sources.napatech_shareinfo import ShareholderRow, ShareholderSnapshot


class MondayDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2025, 1, 6, 13, 0, tzinfo=tz)


class FakeScheduler:
    def __init__(self):
        self.jobs = {
            "monday_top20_14_20250106": object(),
            "monday_top20_15_20250106": object(),
            "monday_top20_16_20250106": object(),
        }
        self.removed: list[str] = []

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.removed.append(job_id)
        self.jobs.pop(job_id, None)

    def add_job(self, *args, **kwargs):
        self.jobs[kwargs["id"]] = object()


class DummySettings:
    napatech_shareinfo_url = "http://example.com"


def _settings():
    return DummySettings()


def test_monday_update_detected_sends_email_and_cancels_retries(monkeypatch) -> None:
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    base = ShareholderSnapshot(
        updated_label="Updated January 1 2025",
        fetched_at=datetime(2025, 1, 1),
        rows=[
            ShareholderRow(rank=1, holder_name="A", shares=100, pct=10.0),
            ShareholderRow(rank=2, holder_name="B", shares=90, pct=9.0),
        ],
        source_url="http://example.com",
    )
    db.insert_shareholder_snapshot(engine, base, attempt_hour=10)

    new = ShareholderSnapshot(
        updated_label="Updated January 6 2025",
        fetched_at=datetime(2025, 1, 6),
        rows=[
            ShareholderRow(rank=1, holder_name="A", shares=110, pct=11.0),
            ShareholderRow(rank=2, holder_name="C", shares=80, pct=8.0),
        ],
        source_url="http://example.com",
    )

    sent = {}

    monkeypatch.setattr(module, "datetime", MondayDateTime)
    monkeypatch.setattr(module, "fetch_shareholders", lambda _url: new)
    monkeypatch.setattr(module, "send_email", lambda _s, subject, body: sent.update(subject=subject, body=body))

    scheduler = FakeScheduler()
    result = module.shareholders_check(engine, _settings(), attempt=14, scheduler=scheduler)

    assert "sent summary email" in result[0]
    assert sent["subject"] == "NAPA Monday Top-20 update"
    assert "Entrants: C" in sent["body"]
    assert scheduler.removed == ["monday_top20_15_20250106", "monday_top20_16_20250106"]


def test_monday_16_unchanged_records_assumption(monkeypatch) -> None:
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    snapshot = ShareholderSnapshot(
        updated_label="Updated January 1 2025",
        fetched_at=datetime(2025, 1, 1),
        rows=[ShareholderRow(rank=1, holder_name="A", shares=100, pct=10.0)],
        source_url="http://example.com",
    )
    db.insert_shareholder_snapshot(engine, snapshot, attempt_hour=10)

    sent = {}

    monkeypatch.setattr(module, "datetime", MondayDateTime)
    monkeypatch.setattr(module, "fetch_shareholders", lambda _url: snapshot)
    monkeypatch.setattr(module, "send_email", lambda _s, subject, body: sent.update(subject=subject, body=body))

    result = module.shareholders_check(engine, _settings(), attempt=16, scheduler=FakeScheduler())

    assert "assumed unchanged" in result[0]
    assert sent["subject"] == "NAPA Monday Top-20 unchanged"

    # The new code records notes="ok" via insert_shareholder_snapshot when no change is detected
    run_rows = engine.execute(
        "SELECT notes FROM shareholder_runs WHERE notes = 'ok' ORDER BY rowid DESC LIMIT 1"
    ).fetchall()
    assert len(run_rows) == 1


def test_force_run_executes_immediately_regardless_of_day(monkeypatch) -> None:
    """Test that force=True bypasses Monday gating and always sends email."""
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    snapshot = ShareholderSnapshot(
        updated_label="Updated January 1 2025",
        fetched_at=datetime(2025, 1, 1),
        rows=[
            ShareholderRow(rank=1, holder_name="A", shares=100, pct=10.0),
            ShareholderRow(rank=2, holder_name="B", shares=90, pct=9.0),
        ],
        source_url="http://example.com",
    )
    db.insert_shareholder_snapshot(engine, snapshot, attempt_hour=10)

    sent = {}

    class WednesdayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Wednesday is weekday 2
            return datetime(2025, 1, 8, 15, 30, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", WednesdayDateTime)
    monkeypatch.setattr(module, "fetch_shareholders", lambda _url: snapshot)
    monkeypatch.setattr(module, "send_email", lambda _s, subject, body: sent.update(subject=subject, body=body))

    result = module.shareholders_check(engine, _settings(), force=True)

    # Verify run was recorded
    assert "Manual force run completed" in result[0]
    
    # Verify email was sent
    assert sent["subject"] == "NAPA Manual Top-20 Check"
    assert "No change detected" in sent["body"] or "no changes detected" in result[0]
    
    # Verify run row was inserted with attempt_hour=15, not Monday check
    run_rows = engine.execute(
        "SELECT attempt_hour, notes FROM shareholder_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchall()
    assert len(run_rows) == 1
    assert run_rows[0]["notes"] == "ok"


def test_force_run_with_change_detects_and_emails(monkeypatch) -> None:
    """Test that force=True detects changes and sends update email."""
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    old_snapshot = ShareholderSnapshot(
        updated_label="Updated January 1 2025",
        fetched_at=datetime(2025, 1, 1),
        rows=[
            ShareholderRow(rank=1, holder_name="A", shares=100, pct=10.0),
            ShareholderRow(rank=2, holder_name="B", shares=90, pct=9.0),
        ],
        source_url="http://example.com",
    )
    db.insert_shareholder_snapshot(engine, old_snapshot, attempt_hour=10)

    new_snapshot = ShareholderSnapshot(
        updated_label="Updated January 8 2025",
        fetched_at=datetime(2025, 1, 8),
        rows=[
            ShareholderRow(rank=1, holder_name="A", shares=110, pct=11.0),
            ShareholderRow(rank=2, holder_name="C", shares=80, pct=8.0),
        ],
        source_url="http://example.com",
    )

    sent = {}

    class WednesdayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 8, 15, 30, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", WednesdayDateTime)
    monkeypatch.setattr(module, "fetch_shareholders", lambda _url: new_snapshot)
    monkeypatch.setattr(module, "send_email", lambda _s, subject, body: sent.update(subject=subject, body=body))

    result = module.shareholders_check(engine, _settings(), force=True)

    # Verify change was detected and email sent
    assert "Top-20 updated" in result[0]
    assert sent["subject"] == "NAPA Monday Top-20 update"
    assert "Entrants: C" in sent["body"]
    
    # Verify snapshot and rows were inserted
    snapshot_rows = engine.execute(
        "SELECT COUNT(*) as cnt FROM shareholder_snapshots"
    ).fetchone()
    assert snapshot_rows["cnt"] == 2


def test_non_monday_gated_run_records_skipped(monkeypatch) -> None:
    """Test that non-Monday runs are gated and recorded as skipped."""
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    sent = {}

    class WednesdayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 8, 15, 30, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", WednesdayDateTime)
    monkeypatch.setattr(module, "send_email", lambda _s, subject, body: sent.update(subject=subject, body=body))

    result = module.shareholders_check(engine, _settings())

    # Verify run was skipped
    assert "Skipped: not Monday" in result[0]
    
    # Verify no email was sent
    assert not sent
    
    # Verify run row was inserted with "skipped:" notes
    run_rows = engine.execute(
        "SELECT notes FROM shareholder_runs WHERE notes LIKE 'skipped:%'"
    ).fetchall()
    assert len(run_rows) == 1
    assert "not Monday" in run_rows[0]["notes"]
    
    # Verify no snapshots were created
    snapshot_rows = engine.execute(
        "SELECT COUNT(*) as cnt FROM shareholder_snapshots"
    ).fetchone()
    assert snapshot_rows["cnt"] == 0


def test_check_records_error_and_reraises(monkeypatch) -> None:
    engine = db.get_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    monkeypatch.setattr(module, "datetime", MondayDateTime)

    def raise_fetch_error(_url):
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(module, "fetch_shareholders", raise_fetch_error)

    with pytest.raises(RuntimeError, match="fetch failed"):
        module.shareholders_check(engine, _settings(), attempt=14, scheduler=FakeScheduler())

    row = engine.execute(
        "SELECT updated_changed_bool, notes FROM shareholder_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["updated_changed_bool"] == 0
    assert str(row["notes"]).startswith("error: fetch failed")

