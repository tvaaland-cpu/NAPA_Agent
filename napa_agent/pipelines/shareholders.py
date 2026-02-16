from __future__ import annotations

import logging
from datetime import datetime, timezone

from napa_agent.config import Settings
from napa_agent.db import fetch_recent, insert_observation
from napa_agent.sources.napatech_shareinfo import fetch_shareholders
from napa_agent.util.diff import compute_holder_deltas

logger = logging.getLogger(__name__)


def run_shareholders_pipeline(engine, settings: Settings) -> list[str]:
    holders = fetch_shareholders(settings.napatech_shareinfo_url)
    if not holders:
        return []

    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%d")
    inserted = insert_observation(
        engine,
        source="shareholders",
        item_id=snapshot_id,
        title=f"Top 20 shareholders {snapshot_id}",
        url=settings.napatech_shareinfo_url,
        payload={"holders": holders},
    )
    if not inserted:
        logger.info("Shareholder snapshot already exists for %s", snapshot_id)

    previous_records = fetch_recent(engine, "shareholders", limit=2)
    if len(previous_records) < 2:
        return []

    current = previous_records[0]["payload"]["holders"]
    previous = previous_records[1]["payload"]["holders"]
    deltas = compute_holder_deltas(previous, current)
    return [f"{d.holder}: {d.change:+,} shares" for d in deltas]
