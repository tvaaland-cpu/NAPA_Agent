from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

E24_URLS = [
    "https://e24.no/emne/napatech",
    "https://e24.no/bors/instrument/NAPA.OSE",
]


class _E24Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._href = ""
        self._title: list[str] = []
        self._in_time = False
        self._time_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        data = dict(attrs)
        if tag == "a":
            self._href = data.get("href", "")
            self._title = []
            self._time_chunks = []
        if tag == "time" and self._href:
            self._in_time = True
            datetime_attr = data.get("datetime", "").strip()
            if datetime_attr:
                self._time_chunks.append(datetime_attr)

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._href:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        self._title.append(cleaned)
        if self._in_time:
            self._time_chunks.append(cleaned)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "time":
            self._in_time = False
            return
        if tag != "a" or not self._href:
            return
        title = re.sub(r"\s+", " ", " ".join(self._title)).strip()
        if title:
            self.items.append(
                {
                    "href": self._href,
                    "title": title,
                    "published_text": " ".join(self._time_chunks).strip(),
                }
            )
        self._href = ""
        self._title = []
        self._time_chunks = []


def _parse_published_at(text: str) -> datetime | None:
    value = text.strip()
    if not value:
        return None

    for token in value.split():
        iso_candidate = token.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    for match in re.findall(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", value):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(match, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def parse_e24_html(html: str, page_url: str) -> list[dict[str, str | datetime | None]]:
    parser = _E24Parser()
    parser.feed(html)

    items: list[dict[str, str | datetime | None]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in parser.items:
        href = candidate["href"].strip()
        title = candidate["title"].strip()
        if not href or not title:
            continue
        full_url = urljoin(page_url, href)
        if "e24.no" not in full_url and not full_url.startswith("/"):
            continue
        if any(skip in full_url for skip in ["/annonser", "/video", "/podkast"]):
            continue
        if "napatech" not in (title + full_url).lower() and "/bors/" not in page_url:
            continue
        dedup_key = (title.lower(), full_url)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        item_id = full_url.rstrip("/").split("/")[-1] or title
        items.append(
            {
                "id": item_id,
                "title": title,
                "url": full_url,
                "published_at": _parse_published_at(candidate.get("published_text", "")),
                "source": "e24",
                "summary": title,
            }
        )
    return items


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_e24_news(urls: list[str] | None = None, timeout: int = 30) -> list[dict[str, str | datetime | None]]:
    pages = urls or E24_URLS
    collected: list[dict[str, str | datetime | None]] = []
    for url in pages:
        request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
        with urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
        collected.extend(parse_e24_html(html, page_url=url))

    dedup: dict[tuple[str, str], dict[str, str | datetime | None]] = {}
    for item in collected:
        key = (str(item["url"]), str(item["id"]))
        dedup[key] = item
    return list(dedup.values())
