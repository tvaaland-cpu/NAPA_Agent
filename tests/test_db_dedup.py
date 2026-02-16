from napa_agent.db import get_engine, init_db, insert_observation


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
