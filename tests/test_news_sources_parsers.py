from pathlib import Path

from napa_agent.sources.e24_sources import parse_e24_html
from napa_agent.sources.finansavisen_ticker import parse_ticker_html


def test_parse_finansavisen_ticker_fixture() -> None:
    html = Path("tests/fixtures/finansavisen_ticker.html").read_text()
    items = parse_ticker_html(html)

    assert len(items) == 2
    assert items[0]["source"] == "finansavisen"
    assert items[0]["title"] == "Napatech stiger på ny kontrakt"
    assert str(items[0]["url"]).startswith("https://www.finansavisen.no/nyheter/")
    assert items[0]["published_at"] is not None

    assert "betalingsmur" in str(items[1]["title"]).lower()
    assert items[1]["published_at"] is None


def test_parse_e24_emne_fixture() -> None:
    html = Path("tests/fixtures/e24_emne_napatech.html").read_text()
    items = parse_e24_html(html, page_url="https://e24.no/emne/napatech")

    assert len(items) == 2
    assert items[0]["source"] == "e24"
    assert str(items[0]["url"]).startswith("https://e24.no/")
    assert items[0]["published_at"] is not None
    assert "annonser" not in str(items[0]["url"])
    assert all("annonser" not in str(item["url"]) for item in items)
