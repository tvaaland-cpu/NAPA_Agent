from datetime import datetime, timedelta, timezone

from napa_agent.util.diff import compute_holder_deltas, rolling_window_changes


def test_compute_holder_deltas() -> None:
    previous = [{"holder": "Investor A", "shares": 100}, {"holder": "Investor B", "shares": 50}]
    current = [{"holder": "Investor A", "shares": 120}, {"holder": "Investor C", "shares": 10}]

    deltas = compute_holder_deltas(previous, current)
    changes = {d.holder: d.change for d in deltas}

    assert changes == {"Investor A": 20, "Investor B": -50, "Investor C": 10}


def test_rolling_window_changes() -> None:
    now = datetime.now(timezone.utc)
    records = [
        {"observed_at": now - timedelta(days=2), "holders": [{"holder": "Investor A", "shares": 100}]},
        {"observed_at": now - timedelta(days=1), "holders": [{"holder": "Investor A", "shares": 110}]},
        {"observed_at": now, "holders": [{"holder": "Investor A", "shares": 140}]},
    ]

    changes = rolling_window_changes(records, days=30)
    assert changes["Investor A"] == 40
