from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

IR_REPORTS_PATH = "reports-and-presentations/"


class _ReportsPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._in_heading = False
        self._current_section = "reports-and-presentations"
        self._heading_text = ""
        self._href = ""
        self._anchor_text = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = True
            self._heading_text = ""
            return
        if tag == "a":
            self._href = dict(attrs).get("href", "")
            self._anchor_text = ""

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_heading:
            self._heading_text += data
        if self._href:
            self._anchor_text += data

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in {"h1", "h2", "h3", "h4"} and self._in_heading:
            heading = self._heading_text.strip()
            if heading:
                # normalize section headings to a slug-like form
                heading_mod = heading.replace("&", "and")
                slug = re.sub(r"[^a-z0-9]+", "-", heading_mod.lower()).strip("-")
                self._current_section = slug or self._current_section
            self._in_heading = False
            self._heading_text = ""
            return

        if tag == "a" and self._href:
            title = " ".join(self._anchor_text.split())
            if title:
                self.items.append(
                    {
                        "title": title,
                        "href": self._href,
                        "section": self._current_section,
                    }
                )
            self._href = ""
            self._anchor_text = ""


def _parse_published_at(text: str) -> datetime | None:
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}/\d{2}/\d{4})",
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def parse_ir_updates(html: str, page_url: str) -> list[dict[str, str | datetime | None]]:
    parser = _ReportsPageParser()
    parser.feed(html)

    items: list[dict[str, str | datetime | None]] = []
    for item in parser.items:
        title = item["title"]
        href = item["href"]
        if not href or not title:
            continue
        if len(title) < 8:
            continue
        if not any(k in title.lower() for k in ["report", "presentation", "release", "interim", "announcement"]):
            continue

        full_url = urljoin(page_url, href)
        item_id = full_url.rstrip("/").split("/")[-1] or title
        items.append(
            {
                "id": item_id,
                "title": title,
                "url": full_url,
                "section": item["section"],
                "published_at": _parse_published_at(title),
                "summary": title,
            }
        )

    dedup = {(str(i["id"]), str(i["url"])): i for i in items}
    return list(dedup.values())[:40]


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_ir_updates(base_url: str, timeout: int = 30) -> list[dict[str, str | datetime | None]]:
    page_url = urljoin(base_url, IR_REPORTS_PATH)
    request = Request(page_url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")

    return parse_ir_updates(html, page_url)
