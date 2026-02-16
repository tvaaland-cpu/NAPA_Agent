from __future__ import annotations

import logging

from napa_agent.config import Settings
from napa_agent.db import insert_observation
from napa_agent.sources.web_search import search_web

logger = logging.getLogger(__name__)


def run_rumor_sweep(engine, settings: Settings) -> int:
    query = "Napatech A/S OR NAPA.OL rumor OR takeover OR strategic review"
    items = search_web(query)

    inserted = 0
    for item in items:
        if insert_observation(
            engine,
            source="rumor_sweep",
            item_id=item.get("id", item.get("url", item.get("title", ""))),
            title=item.get("title", "untitled"),
            url=item.get("url", ""),
            payload=item,
        ):
            inserted += 1

    logger.info("Rumor sweep completed with %s new observations", inserted)
    return inserted
