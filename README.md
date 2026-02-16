# NAPA Agent

Python monitoring agent for Napatech A/S (NAPA.OL), focused on shareholder changes, company updates, and rumor monitoring.

## Quick start

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .`
3. `cp .env.example .env` and update SMTP credentials
4. Run scheduler: `python -m napa_agent.scripts.run` or `python scripts/run.py`
5. Run tests: `pytest`

## Monday Top-20 monitoring behavior (Europe/Oslo)

- Primary job runs every Monday at `13:00` (`shareholders_check(attempt=13)`).
- If unchanged at 13:00, one-off retries are scheduled for `14:00`, `15:00`, and `16:00`.
- If an update is detected at any attempt:
  - a new snapshot is stored,
  - week-over-week + rolling-window deltas are computed,
  - a Monday summary email is sent,
  - remaining retries for that Monday are canceled.
- If still unchanged by 16:00:
  - the run is recorded in `shareholder_runs` with `notes='assumed unchanged'`,
  - **no duplicate unchanged snapshot copy is stored** (the previous snapshot remains the baseline and is referenced in the summary email).

The Monday report includes entrants/exits, rank changes, biggest share changes, top-20 totals (shares and pct), and rolling comparisons to the snapshots nearest to 1/3/6/9/12 months ago.
