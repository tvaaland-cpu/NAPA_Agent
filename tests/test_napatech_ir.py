from datetime import datetime, timezone
from pathlib import Path

from napa_agent.sources.napatech_ir import parse_ir_updates


def test_parse_reports_fixture_has_absolute_urls_and_items():
    html = Path("tests/fixtures/reports_and_presentations.html").read_text()
    page_url = "https://www.napatech.com/investor-relations/reports-and-presentations/"
    items = parse_ir_updates(html, page_url)

    assert isinstance(items, list)
    assert len(items) >= 1

    for item in items:
        assert "title" in item
        assert "url" in item
        assert item["url"].startswith("http"), "URL should be absolute"
        assert "section" in item
        assert item["section"] == "reports-and-presentations"
        # published_at can be None, but if present should be a datetime
        if item.get("published_at") is not None:
            assert isinstance(item["published_at"], datetime)
