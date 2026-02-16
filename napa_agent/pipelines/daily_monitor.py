from __future__ import annotations

import logging

from napa_agent.config import Settings
from napa_agent.db import insert_observation
from napa_agent.notify.emailer import send_email
from napa_agent.sources.euronext_news import fetch_company_news
from napa_agent.sources.napatech_ir import fetch_ir_updates

logger = logging.getLogger(__name__)


def run_daily_monitor(engine, settings: Settings) -> int:
    discovered = 0
    new_items: list[str] = []

    for item in fetch_company_news(settings.euronext_news_url):
        if insert_observation(
            engine,
            source="euronext_news",
            item_id=item["id"],
            title=item["title"],
            url=item["url"],
            payload=item,
        ):
            discovered += 1
            new_items.append(f"- [Euronext] {item['title']} ({item['url']})")

    for item in fetch_ir_updates(settings.napatech_ir_base_url):
        if insert_observation(
            engine,
            source="napatech_ir",
            item_id=item["id"],
            title=item["title"],
            url=item["url"],
            payload=item,
        ):
            discovered += 1
            new_items.append(f"- [IR/{item['section']}] {item['title']} ({item['url']})")

    if new_items:
        body = "New Napatech updates detected:\n\n" + "\n".join(new_items)
        send_email(settings, "Napatech daily monitor update", body)
        logger.info("Sent daily monitor email with %s items", len(new_items))

    return discovered
