from __future__ import annotations

import logging
from datetime import datetime, timezone

from napa_agent.config import Settings
from napa_agent.db import confirm_rumors_with_tier1_item, insert_news_item
from napa_agent.notify.emailer import send_email
from napa_agent.sources.euronext_news import fetch_company_news
from napa_agent.sources.napatech_ir import fetch_ir_updates
from napa_agent.sources.web_search import search_web

# Optional sources: import if available, otherwise provide no-op fallbacks
try:
    from napa_agent.sources.e24_sources import fetch_e24_news  # type: ignore
except Exception:
    def fetch_e24_news() -> list[dict]:
        return []

try:
    from napa_agent.sources.finansavisen_ticker import fetch_ticker_news  # type: ignore
except Exception:
    def fetch_ticker_news() -> list[dict]:
        return []
from napa_agent.sources.napatech_ir import fetch_ir_updates
from napa_agent.sources.web_search import search_web

logger = logging.getLogger(__name__)


def run_daily_monitor(engine, settings: Settings) -> int:
    discovered = 0
    discovered_at = datetime.now(timezone.utc)
    euronext_items: list[str] = []
    e24_items: list[str] = []
    finansavisen_items: list[str] = []
    ir_items: list[str] = []

    try:
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
                euronext_items.append(f"- {item['title']} ({item['url']})")
                if news_id is not None:
                    confirm_rumors_with_tier1_item(engine, news_id)
    except Exception:
        logger.exception("Failed fetching Euronext news")

    try:
        for item in fetch_e24_news():
            inserted, _ = insert_news_item(
                engine,
                url=item["url"],
                title=item["title"],
                published_at=item.get("published_at"),
                discovered_at=discovered_at,
                source_tier=2,
                tags=["e24"],
                summary=item.get("summary", item["title"]),
                rumor=True,
            )
            if inserted:
                discovered += 1
                e24_items.append(f"- {item['title']} ({item['url']})")
    except Exception:
        logger.exception("Failed fetching E24 news")

    try:
        for item in fetch_ticker_news():
            inserted, _ = insert_news_item(
                engine,
                url=item["url"],
                title=item["title"],
                published_at=item.get("published_at"),
                discovered_at=discovered_at,
                source_tier=2,
                tags=["finansavisen"],
                summary=item.get("summary", item["title"]),
                rumor=True,
            )
            if inserted:
                discovered += 1
                finansavisen_items.append(f"- {item['title']} ({item['url']})")
    except Exception:
        logger.exception("Failed fetching Finansavisen ticker")

    try:
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
                ir_items.append(f"- {item['title']} ({item['url']})")
    except Exception:
        logger.exception("Failed fetching Napatech IR updates")

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

    body_lines = ["Daily Napatech digest", ""]
    body_lines.append("Euronext (Tier 1):")
    body_lines.extend(euronext_items or ["- None"])
    body_lines.append("")
    body_lines.append("E24:")
    body_lines.extend(e24_items or ["- None"])
    body_lines.append("")
    body_lines.append("Finansavisen:")
    body_lines.extend(finansavisen_items or ["- None"])
    body_lines.append("")
    body_lines.append("Napatech IR:")
    body_lines.extend(ir_items or ["- None"])
    body_lines.append("")
    body_lines.append(f"Partner/rumor sweep: {search_note}")

    try:
        send_email(settings, "Napatech daily monitor digest", "\n".join(body_lines))
        logger.info(
            "Sent daily monitor digest (euronext=%s e24=%s finansavisen=%s ir=%s)",
            len(euronext_items),
            len(e24_items),
            len(finansavisen_items),
            len(ir_items),
        )
    except Exception:
        logger.exception("Failed to send daily monitor digest; continuing")

    return discovered
