from pathlib import Path

from napa_agent.sources.napatech_shareinfo import parse_top20_html


def test_parse_top20_html_fixture() -> None:
    html = Path("tests/fixtures/top20_shareholders.html").read_text()
    result = parse_top20_html(html)

    assert len(result) == 3
    assert result[0] == {"holder": "Investor A", "shares": 1200000}
    assert result[1]["shares"] == 950000
