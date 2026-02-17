from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

_DATE_PATTERNS = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}\.\d{2}\.\d{4})"]
_NEWS_KEYWORDS = ("press", "release", "announcement", "company news", "inside information", "napatech")


class _NewsLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._time_text: list[str] = []
        self._in_time = False

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        data = dict(attrs)
        if tag == "a":
            self._href = data.get("href", "")
            self._text = []
            self._time_text = []
        if tag == "time" and self._href:
            self._in_time = True
            datetime_attr = data.get("datetime", "").strip()
            if datetime_attr:
                self._time_text.append(datetime_attr)

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._href:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        self._text.append(cleaned)
        if self._in_time:
            self._time_text.append(cleaned)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "time":
            self._in_time = False
            return
        if tag != "a" or not self._href:
            return
        title = re.sub(r"\s+", " ", " ".join(self._text)).strip()
        if title:
            self.items.append(
                {
                    "title": title,
                    "href": self._href,
                    "published_text": " ".join(self._time_text).strip(),
                }
            )
        self._href = ""
        self._text = []
        self._time_text = []


def _parse_published_at(text: str) -> datetime | None:
    raw = text.strip()
    if not raw:
        return None

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    for pattern in _DATE_PATTERNS:
        match = re.search(pattern, raw)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _is_candidate_news(title: str, full_url: str) -> bool:
    low = f"{title} {full_url}".lower()
    if any(keyword in low for keyword in _NEWS_KEYWORDS):
        return True
    if full_url.lower().endswith(".pdf"):
        return True
    return "/news/" in low or "/press" in low


def parse_company_news(html: str, base_url: str) -> list[dict[str, str | datetime | None]]:
    parser = _NewsLinkParser()
    parser.feed(html)

    items: list[dict[str, str | datetime | None]] = []
    dedup: dict[tuple[str, str], dict[str, str | datetime | None]] = {}
    for candidate in parser.items:
        title = candidate["title"].strip()
        href = candidate["href"].strip()
        if not title or not href:
            continue
        full_url = urljoin(base_url, href)
        if "euronext" not in full_url and not full_url.lower().endswith(".pdf"):
            continue
        if not _is_candidate_news(title, full_url):
            continue

        item_id = full_url.rstrip("/").split("/")[-1] or title
        item = {
            "id": item_id,
            "title": title,
            "url": full_url,
            "published_at": _parse_published_at(candidate.get("published_text", "") or title),
            "summary": title,
        }
        dedup[(str(item["url"]), str(item["id"]))] = item

    items.extend(dedup.values())
    return items[:40]


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_company_news(url: str, timeout: int = 30) -> list[dict[str, str | datetime | None]]:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_company_news(html, base_url=url)
