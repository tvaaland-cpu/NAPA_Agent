from datetime import datetime

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

    note_rows = engine.execute(
        "SELECT notes FROM shareholder_runs WHERE notes = 'assumed unchanged'"
    ).fetchall()
    assert len(note_rows) == 1
