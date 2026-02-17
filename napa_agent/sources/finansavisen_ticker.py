from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

FINANSAVISEN_TICKER_URL = "https://www.finansavisen.no/ticker/NAPA/nyheter"


class _TickerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._in_li = False
        self._in_time = False
        self._current_href = ""
        self._current_title: list[str] = []
        self._current_time: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        data = dict(attrs)
        if tag == "li":
            self._in_li = True
            self._current_href = ""
            self._current_title = []
            self._current_time = []
        if not self._in_li:
            return
        if tag == "a" and not self._current_href:
            self._current_href = data.get("href", "")
        if tag == "time":
            self._in_time = True
            datetime_attr = data.get("datetime", "").strip()
            if datetime_attr:
                self._current_time.append(datetime_attr)

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._in_li:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        if self._in_time:
            self._current_time.append(cleaned)
        else:
            self._current_title.append(cleaned)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "time":
            self._in_time = False
        if tag != "li":
            return
        title = " ".join(self._current_title).strip()
        if self._current_href and title:
            self.items.append(
                {
                    "title": re.sub(r"\s+", " ", title),
                    "href": self._current_href,
                    "published_text": " ".join(self._current_time).strip(),
                }
            )
        self._in_li = False
        self._in_time = False


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for token in text.split():
        iso_candidate = token.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_ticker_html(html: str, base_url: str = FINANSAVISEN_TICKER_URL) -> list[dict[str, str | datetime | None]]:
    parser = _TickerParser()
    parser.feed(html)

    items: list[dict[str, str | datetime | None]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in parser.items:
        title = candidate["title"].strip()
        href = candidate["href"].strip()
        if not title or not href:
            continue
        full_url = urljoin(base_url, href)
        item_id = full_url.rstrip("/").split("/")[-1] or title
        dedup_key = (title.lower(), full_url)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        items.append(
            {
                "id": item_id,
                "title": title,
                "url": full_url,
                "published_at": _parse_datetime(candidate.get("published_text", "")),
                "source": "finansavisen",
                "summary": title,
            }
        )
    return items


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_ticker_news(url: str = FINANSAVISEN_TICKER_URL, timeout: int = 30) -> list[dict[str, str | datetime | None]]:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_ticker_html(html, base_url=url)
