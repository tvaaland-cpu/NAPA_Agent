from datetime import datetime, timezone
from pathlib import Path

from napa_agent.sources import napatech_ir
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


class _DummyResponse:
    def __init__(self, html: str) -> None:
        self._payload = html.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def test_fetch_ir_updates_builds_reports_url_without_double_append(monkeypatch) -> None:
    html = "<html><body><a href='/investor-relations/reports-and-presentations/annual-report-2025/'>Annual Report 2025</a></body></html>"
    requested_urls: list[str] = []

    def fake_urlopen(request, timeout=30):
        del timeout
        requested_urls.append(request.full_url)
        return _DummyResponse(html)

    monkeypatch.setattr(napatech_ir, "urlopen", fake_urlopen)

    napatech_ir.fetch_ir_updates("https://www.napatech.com/investor-relations")
    napatech_ir.fetch_ir_updates("https://www.napatech.com/investor-relations/reports-and-presentations/")

    assert requested_urls[0] == "https://www.napatech.com/investor-relations/reports-and-presentations/"
    assert requested_urls[1] == "https://www.napatech.com/investor-relations/reports-and-presentations/"
