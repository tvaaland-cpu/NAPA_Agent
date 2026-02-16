from datetime import datetime, timezone
from pathlib import Path

from napa_agent.sources.napatech_shareinfo import parse_shareholder_snapshot


def test_parse_top20_html_fixture() -> None:
    html = Path("tests/fixtures/share_information.html").read_text()
    snapshot = parse_shareholder_snapshot(
        html,
        source_url="https://www.napatech.com/investor-relations/share-information/",
        fetched_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
    )

    assert snapshot.updated_label == "Updated January 9. 2025"
    assert snapshot.source_url.endswith("/share-information/")
    assert len(snapshot.rows) == 20

    assert snapshot.rows[0].rank == 1
    assert snapshot.rows[0].holder_name == "Investor A"
    assert snapshot.rows[0].shares == 4_250_000
    assert snapshot.rows[1].pct == 14.2
    assert snapshot.rows[2].shares == 3_450_000
