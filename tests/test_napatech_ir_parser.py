from pathlib import Path

from napa_agent.sources.napatech_ir import parse_ir_updates


def test_parse_reports_presentations_fixture() -> None:
    html = Path("tests/fixtures/napatech_reports_presentations.html").read_text()
    items = parse_ir_updates(
        html,
        page_url="https://www.napatech.com/investor-relations/reports-and-presentations/",
    )

    assert len(items) >= 1
    assert all(str(item["url"]).startswith("https://") for item in items)

