from datetime import datetime, timezone
from pathlib import Path

from napa_agent.sources.euronext_news import parse_company_news


def test_parse_company_news_filters_junk_and_requires_dates() -> None:
    html = Path("tests/fixtures/euronext_company_page_mixed.html").read_text()
    items = parse_company_news(
        html,
        base_url="https://live.euronext.com/en/product/equities/DK0060520450-XCSE/company-information",
    )

    assert len(items) == 2

    urls = {str(item["url"]) for item in items}
    assert "https://www.euronext.com/news/company-announcement-napatech-q4-2025-results" in urls
    assert "https://live.euronext.com/news/inside-information-napatech-board-update" in urls

    rejected = {
        "https://live.euronext.com/en/products/equities/equity-espresso",
        "https://live.euronext.com/en/products/indices/announcements",
        "https://live.euronext.com/en/product/equities/DK0060520450-XCSE/company-information",
        "https://www.euronext.com/en/esg/reporting",
        "https://www.euronext.com/news/this-should-be-skipped-no-date",
    }
    assert rejected.isdisjoint(urls)

    for item in items:
        assert item["published_at"] is not None
        assert isinstance(item["published_at"], datetime)
        assert item["published_at"].tzinfo == timezone.utc
        assert item["tags"] == ["euronext"]
