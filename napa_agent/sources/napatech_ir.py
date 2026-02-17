from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag != "a":
            return
        self._href = dict(attrs).get("href", "")
        self._text = ""

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        self._text += data

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "a" and self._href:
            self.links.append((self._text.strip(), self._href))
            self._href = ""
            self._text = ""


def _parse_published_at(text: str) -> datetime | None:
    patterns = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_ir_updates(base_url: str, timeout: int = 30) -> list[dict[str, str | datetime | None]]:
    request = Request(base_url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")

    parser = _LinkParser()
    parser.feed(html)

    items: list[dict[str, str | datetime | None]] = []
    for title, href in parser.links:
        if not href or not title:
            continue
        if len(title) < 8:
            continue
        if not any(k in title.lower() for k in ["report", "presentation", "release", "interim", "announcement"]):
            continue
        full_url = urljoin(base_url, href)
        item_id = full_url.rstrip("/").split("/")[-1] or title
        items.append(
            {
                "id": item_id,
                "title": title,
                "url": full_url,
                "section": "reports-and-presentations",
                "published_at": _parse_published_at(title),
                "summary": title,
            }
        )

    dedup = {(str(i["id"]), str(i["url"])): i for i in items}
    return list(dedup.values())[:40]
