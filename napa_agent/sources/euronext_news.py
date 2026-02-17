from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

_DATE_PATTERNS = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}\.\d{2}\.\d{4})"]
_NEWS_KEYWORDS = ("press", "release", "announcement", "company news", "inside information", "napatech")
_BOILERPLATE_TITLES = {"read more", "learn more", "view more", "more", "details"}
_REJECTED_URL_PARTS = (
    "live.euronext.com/en/products/",
    "live.euronext.com/en/product/",
    "equity-espresso",
    "indices/announcements",
)


class _NewsLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._time_text: list[str] = []
        self._anchor_context_date = ""
        self._in_time = False
        self._latest_date_text = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        data = dict(attrs)
        if tag == "a":
            self._href = data.get("href", "")
            self._text = []
            self._time_text = []
            self._anchor_context_date = self._latest_date_text
        if tag == "time" and self._href:
            self._in_time = True
            datetime_attr = data.get("datetime", "").strip()
            if datetime_attr:
                self._time_text.append(datetime_attr)
        elif tag == "time":
            self._in_time = True
            datetime_attr = data.get("datetime", "").strip()
            if datetime_attr:
                self._latest_date_text = datetime_attr

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        cleaned = data.strip()
        if not cleaned:
            return
        if self._href:
            self._text.append(cleaned)
        if self._in_time:
            if self._href:
                self._time_text.append(cleaned)
            else:
                self._latest_date_text = cleaned
        elif _parse_published_at(cleaned) is not None:
            self._latest_date_text = cleaned

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
                    "published_text": " ".join(self._time_text).strip() or self._anchor_context_date,
                }
            )
        self._href = ""
        self._text = []
        self._time_text = []
        self._anchor_context_date = ""


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


def _is_rejected_url(full_url: str) -> bool:
    lowered = full_url.lower()
    return any(part in lowered for part in _REJECTED_URL_PARTS)


def _is_rejected_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    return normalized in _BOILERPLATE_TITLES


def _has_news_path(full_url: str, discovered_news_prefixes: set[str]) -> bool:
    parsed = urlparse(full_url)
    path = parsed.path.lower()
    if "/news/" in path:
        return True
    return any(path.startswith(prefix) for prefix in discovered_news_prefixes)


def _discover_news_prefixes(urls: list[str]) -> set[str]:
    prefixes: set[str] = set()
    for full_url in urls:
        if _is_rejected_url(full_url):
            continue
        parsed = urlparse(full_url)
        segments = [segment for segment in parsed.path.lower().split("/") if segment]
        if not segments:
            continue
        for idx, segment in enumerate(segments):
            if "news" in segment or "announcement" in segment:
                prefix = "/" + "/".join(segments[: idx + 1]) + "/"
                prefixes.add(prefix)
                break
    return prefixes


def parse_company_news(html: str, base_url: str) -> list[dict[str, object]]:
    parser = _NewsLinkParser()
    parser.feed(html)

    items: list[dict[str, object]] = []
    candidate_urls = [urljoin(base_url, item["href"].strip()) for item in parser.items if item["href"].strip()]
    discovered_news_prefixes = _discover_news_prefixes(candidate_urls)
    dedup: dict[tuple[str, str], dict[str, object]] = {}
    for candidate in parser.items:
        title = candidate["title"].strip()
        href = candidate["href"].strip()
        if not title or not href:
            continue
        if _is_rejected_title(title):
            continue
        full_url = urljoin(base_url, href)
        if _is_rejected_url(full_url):
            continue
        parsed_url = urlparse(full_url)
        host = parsed_url.netloc.lower()
        if "euronext.com" not in host and not full_url.lower().endswith(".pdf"):
            continue
        if not _has_news_path(full_url, discovered_news_prefixes):
            continue
        if not _is_candidate_news(title, full_url):
            continue
        published_at = _parse_published_at(candidate.get("published_text", "") or title)
        if published_at is None:
            continue

        item_id = full_url.rstrip("/").split("/")[-1] or title
        item = {
            "id": item_id,
            "title": title,
            "url": full_url,
            "published_at": published_at,
            "summary": title,
            "tags": ["euronext"],
        }
        dedup[(str(item["url"]), str(item["id"]))] = item

    items.extend(dedup.values())
    return items[:40]


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_company_news(url: str, timeout: int = 30) -> list[dict[str, object]]:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_company_news(html, base_url=url)
