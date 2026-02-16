from datetime import datetime, timezone

from napa_agent.db import (
    confirm_rumors_with_tier1_item,
    get_engine,
    init_db,
    insert_news_item,
    set_rumor_status,
)


def test_insert_news_item_dedup_url_and_hash() -> None:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    inserted_first, _ = insert_news_item(
        engine,
        url="https://example.com/a",
        title="Napatech release",
        published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        discovered_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        source_tier=1,
        tags=["official_release"],
        summary="Napatech release",
        rumor=False,
    )
    inserted_second, _ = insert_news_item(
        engine,
        url="https://example.com/a",
        title="Duplicate url",
        published_at=None,
        discovered_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        source_tier=2,
        tags=["ir"],
        summary="other",
        rumor=True,
    )
    inserted_third, _ = insert_news_item(
        engine,
        url="https://example.com/b",
        title="Napatech release",
        published_at=None,
        discovered_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        source_tier=2,
        tags=["ir"],
        summary="Napatech release",
        rumor=True,
    )

    assert inserted_first is True
    assert inserted_second is False
    assert inserted_third is False


def test_rumor_status_transitions_and_confirmation() -> None:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    _, rumor_news_item_id = insert_news_item(
        engine,
        url="https://news.example/rumor",
        title="Napatech strategic partnership rumor",
        published_at=None,
        discovered_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        source_tier=3,
        tags=["rumor"],
        summary="Claim about strategic partnership",
        rumor=True,
    )
    rumor_row = engine.execute("SELECT id, status FROM rumors WHERE news_item_id = ?", (rumor_news_item_id,)).fetchone()
    assert rumor_row is not None
    assert rumor_row["status"] == "new"

    set_rumor_status(engine, rumor_row["id"], "watch")
    updated = engine.execute("SELECT status FROM rumors WHERE id = ?", (rumor_row["id"],)).fetchone()
    assert updated is not None
    assert updated["status"] == "watch"

    _, tier1_news_item_id = insert_news_item(
        engine,
        url="https://euronext.example/official",
        title="Napatech announces strategic partnership",
        published_at=None,
        discovered_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
        source_tier=1,
        tags=["official_release"],
        summary="Official confirmation",
        rumor=False,
    )
    confirmed_count = confirm_rumors_with_tier1_item(engine, int(tier1_news_item_id))

    final_row = engine.execute("SELECT status FROM rumors WHERE id = ?", (rumor_row["id"],)).fetchone()
    assert confirmed_count == 1
    assert final_row is not None
    assert final_row["status"] == "confirmed"
