from __future__ import annotations

from napa_agent.config import Settings
from napa_agent.db import insert_shareholder_snapshot
from napa_agent.sources.napatech_shareinfo import fetch_shareholders


def run_shareholders_pipeline(engine, settings: Settings) -> list[str]:
    snapshot = fetch_shareholders(settings.napatech_shareinfo_url)
    if not snapshot.rows:
        return []

    changed, snapshot_id = insert_shareholder_snapshot(engine, snapshot, attempt_hour=snapshot.fetched_at.hour)
    if not changed:
        return ["Shareholder snapshot unchanged"]

    return [f"Stored shareholder snapshot #{snapshot_id} with {len(snapshot.rows)} rows"]
