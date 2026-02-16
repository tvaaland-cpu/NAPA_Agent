from __future__ import annotations

import logging
from datetime import datetime, timezone

from napa_agent.config import Settings
from napa_agent.db import confirm_rumors_with_tier1_item, insert_news_item
from napa_agent.notify.emailer import send_email
from napa_agent.sources.euronext_news import fetch_company_news
from napa_agent.sources.napatech_ir import fetch_ir_updates
from napa_agent.sources.web_search import search_web

logger = logging.getLogger(__name__)


def run_daily_monitor(engine, settings: Settings) -> int:
    discovered = 0
    tier1_items: list[str] = []
    tier2_items: list[str] = []
    discovered_at = datetime.now(timezone.utc)

    for item in fetch_company_news(settings.euronext_news_url):
        inserted, news_id = insert_news_item(
            engine,
            url=item["url"],
            title=item["title"],
            published_at=item.get("published_at"),
            discovered_at=discovered_at,
            source_tier=1,
            tags=["official_release", "euronext"],
            summary=item.get("summary", item["title"]),
            rumor=False,
        )
        if inserted:
            discovered += 1
            tier1_items.append(f"- {item['title']} ({item['url']})")
            if news_id is not None:
                confirm_rumors_with_tier1_item(engine, news_id)

    for item in fetch_ir_updates(settings.napatech_ir_base_url):
        inserted, _ = insert_news_item(
            engine,
            url=item["url"],
            title=item["title"],
            published_at=item.get("published_at"),
            discovered_at=discovered_at,
            source_tier=2,
            tags=["ir", item["section"]],
            summary=item.get("summary", item["title"]),
            rumor=True,
        )
        if inserted:
            discovered += 1
            tier2_items.append(f"- {item['title']} ({item['url']})")

    rumor_query = "Napatech partner OR Napatech takeover OR Napatech strategic review"
    rumor_items, search_note = search_web(rumor_query, settings.web_search_endpoint)
    for item in rumor_items:
        inserted, _ = insert_news_item(
            engine,
            url=item.get("url", ""),
            title=item.get("title", "untitled"),
            published_at=item.get("published_at"),
            discovered_at=discovered_at,
            source_tier=3,
            tags=["rumor", "web_search"],
            summary=item.get("summary", item.get("title", "")),
            rumor=True,
        )
        if inserted:
            discovered += 1

    if not tier1_items and not tier2_items:
        body_lines = ["No new items since last run"]
    else:
        body_lines = ["Daily Napatech digest", ""]
        body_lines.append("Tier 1 (Euronext official releases):")
        body_lines.extend(tier1_items or ["- None"])
        body_lines.append("")
        body_lines.append("Tier 2 (Napatech IR pages):")
        body_lines.extend(tier2_items or ["- None"])

    body_lines.append("")
    body_lines.append(f"Partner/rumor sweep: {search_note}")

    send_email(settings, "Napatech daily monitor digest", "\n".join(body_lines))
    logger.info("Sent daily monitor digest (tier1=%s tier2=%s)", len(tier1_items), len(tier2_items))

    return discovered
