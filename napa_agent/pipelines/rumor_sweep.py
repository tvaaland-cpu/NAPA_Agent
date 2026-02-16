from __future__ import annotations

import logging
from datetime import datetime, timezone

from napa_agent.config import Settings
from napa_agent.db import insert_news_item
from napa_agent.sources.web_search import search_web

logger = logging.getLogger(__name__)


def run_rumor_sweep(engine, settings: Settings) -> int:
    query = "Napatech A/S OR NAPA.OL rumor OR takeover OR strategic review"
    items, note = search_web(query, settings.web_search_endpoint)

    inserted = 0
    now = datetime.now(timezone.utc)
    for item in items:
        created, _ = insert_news_item(
            engine,
            url=item.get("url", ""),
            title=item.get("title", "untitled"),
            published_at=item.get("published_at"),
            discovered_at=now,
            source_tier=3,
            tags=["rumor", "web_search"],
            summary=item.get("summary", item.get("title", "")),
            rumor=True,
        )
        if created:
            inserted += 1

    logger.info("Rumor sweep completed with %s new observations (%s)", inserted, note)
    return inserted
