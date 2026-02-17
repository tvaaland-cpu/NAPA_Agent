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

    # Check metadata
    assert snapshot.updated_label == "Updated February 13. 2026"
    assert snapshot.source_url.endswith("/share-information/")
    
    # Check exactly 20 rows (filters out summary rows)
    assert len(snapshot.rows) == 20, f"Expected 20 rows, got {len(snapshot.rows)}"
    
    # Check first row (SUNDT AS)
    assert snapshot.rows[0].rank == 1
    assert snapshot.rows[0].holder_name == "SUNDT AS"
    assert snapshot.rows[0].shares == 18257427
    assert snapshot.rows[0].pct == 16.58
    assert snapshot.rows[0].holder_type == "Ordinary"
    assert snapshot.rows[0].country == "Norway"
    
    # Check holder_name is not purely numeric
    for row in snapshot.rows:
        assert not row.holder_name.isdigit(), f"Holder name is purely numeric: {row.holder_name}"
    
    # Check totals are reasonable (should be ~70% for top 20)
    total_pct = sum(row.pct for row in snapshot.rows)
    assert total_pct <= 100.5, f"Total percentage {total_pct:.2f}% is over 100.5%"
    assert total_pct >= 60.0, f"Total percentage {total_pct:.2f}% is below 60% (seems wrong)"
    
    # Check last row (DALLAS ASSET MANAGEMENT AS - rank 20)
    assert snapshot.rows[19].rank == 20
    assert snapshot.rows[19].holder_name == "DALLAS ASSET MANAGEMENT AS"
    assert snapshot.rows[19].shares == 1039340
    assert snapshot.rows[19].pct == 0.94


def test_parse_header_variant_fixture_prefers_top20_shape() -> None:
    html = Path("tests/fixtures/share_information_header_variants.html").read_text()
    snapshot = parse_shareholder_snapshot(
        html,
        source_url="https://www.napatech.com/investor-relations/share-information/",
        fetched_at=datetime(2026, 2, 13, tzinfo=timezone.utc),
    )

    assert len(snapshot.rows) == 20
    assert snapshot.rows[0].rank == 1
    assert snapshot.rows[0].holder_name == "Alpha AS"
    assert snapshot.rows[19].rank == 20
    assert snapshot.rows[19].holder_name == "Upsilon AS"
